import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import NON_WINE_REPLY
from app.llm_client import get_llm
from app.query_engine import (
    apply_question_geo_to_plan,
    apply_question_price_to_plan,
    default_query_plan,
    filter_wines_heuristic,
    filter_wines_with_plan,
    generate_query_plan,
)
from app.repository import WineRepository, normalize_text
from app.schemas import AskResponse


def fix_wine_question_typos(text: str) -> str:
    """Fix common STT/typo patterns so intent and ``question_is_wine_related`` stay correct."""
    s = text.strip()
    s = re.sub(r"\b(some|any|a few|just)\s+wise\b", r"\1 wines", s, flags=re.IGNORECASE)
    s = re.sub(
        r"\bwise\s+(around|under|over|near|about|for|that|in|from|at)\b",
        r"wines \1",
        s,
        flags=re.IGNORECASE,
    )
    return s


def fallback_answer(question: str, wines: list[dict[str, Any]]) -> str:
    if not wines:
        return (
            "I could not find matching wines in this catalog for that request. "
            "Try specifying color, varietal, region, or a price range."
        )
    q = normalize_text(question)
    top = wines[:3]
    labels = []
    for wine in top:
        name = wine.get("name", "Unknown wine")
        price = wine.get("price")
        price_text = (
            f"${float(price):.2f}" if isinstance(price, (int, float)) else "an unknown price"
        )
        country = wine.get("country") or "unknown origin"
        labels.append(f"{name} ({price_text}, {country})")

    if any(term in q for term in {"budget", "cheap", "affordable", "value"}):
        return (
            f"For a budget-friendly pick, start with {labels[0]}. "
            f"Other strong value options are {', '.join(labels[1:])}."
            if len(labels) > 1
            else f"For a budget-friendly pick, start with {labels[0]}."
        )

    return (
        f"From this catalog, top matches are {', '.join(labels)}. "
        "Tell me your preferred color, region, or price ceiling and I can refine further."
    )


def reorder_wines_by_answer(answer: str, wines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Put wines whose names appear in the answer first, in order of first mention."""
    if not answer or not wines:
        return wines
    lower = answer.lower()
    scored: list[tuple[int, int]] = []
    for i, w in enumerate(wines):
        name = (w.get("name") or "").strip()
        if not name:
            scored.append((10_000 + i, i))
            continue
        pos = lower.find(name.lower())
        if pos < 0:
            scored.append((5_000 + i, i))
        else:
            scored.append((pos, i))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [wines[i] for _, i in scored]


def answer_references_primary_wines(answer: str, primary_wines: list[dict[str, Any]]) -> bool:
    if not answer or not primary_wines:
        return False
    answer_normalized = normalize_text(answer)
    primary_names = [normalize_text(w.get("name", "")) for w in primary_wines]
    if any(name and name in answer_normalized for name in primary_names):
        return True

    # Fuzzy check: allow partial mentions of meaningful wine name tokens.
    for name in primary_names:
        tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", name)
            if len(token) >= 8 and token not in {"wine", "cellars", "vineyards"}
        ]
        if tokens and any(token in answer_normalized for token in tokens):
            return True
    return False


def answer_mentions_catalog_bottle_outside_context(
    answer: str, context_wines: list[dict[str, Any]], repository: WineRepository
) -> bool:
    """True if the answer contains a full catalog wine name that is not in ``context_wines``."""
    if not answer or repository.df.empty:
        return False
    a = normalize_text(answer)
    allowed = {normalize_text(w.get("name", "")) for w in context_wines if w.get("name")}
    allowed.discard("")
    min_len = 10
    for raw in repository.df["Name"].astype(str).unique():
        nn = normalize_text(raw)
        if len(nn) < min_len:
            continue
        if nn not in a:
            continue
        if nn not in allowed:
            return True
    return False


class WineAssistant:
    def __init__(self) -> None:
        self.repository = WineRepository()

    def load_data(self) -> None:
        self.repository.load()

    def health(self) -> dict[str, Any]:
        from app.config import LLM_PROVIDER, OLLAMA_MODEL

        return {
            "status": "ok",
            "wines_loaded": int(len(self.repository.df)),
            "llm_provider": LLM_PROVIDER,
            "ollama_model": OLLAMA_MODEL,
        }

    def ask(self, question: str) -> AskResponse:
        question = fix_wine_question_typos(question.strip())
        llm = get_llm()
        llm_plan = generate_query_plan(question, self.repository, llm)
        plan = llm_plan or default_query_plan(question, self.repository)
        plan = apply_question_price_to_plan(plan, question)
        plan = apply_question_geo_to_plan(plan, question, self.repository)

        if not plan.get("is_wine_related", True):
            return AskResponse(answer=NON_WINE_REPLY, wines=[])

        if plan.get("needs_clarification") and plan.get("clarification_question"):
            clarification = str(plan.get("clarification_question")).strip()
            return AskResponse(answer=clarification, wines=[])

        filtered = filter_wines_with_plan(plan, self.repository)
        if filtered.empty:
            filtered = filter_wines_heuristic(question, self.repository)

        wines = self.repository.wines_to_cards(filtered)
        primary_wines = wines[:3]
        if not wines:
            return AskResponse(answer=fallback_answer(question, wines), wines=[])

        system_prompt = (
            "You are a wine assistant for a wine explorer app.\n"
            "Rules:\n"
            "1) Answer only from the provided wine data context.\n"
            "2) Never invent facts or bottles not in the context.\n"
            "3) Keep the response concise: 2-4 sentences for voice output.\n"
            "4) If the user asks something not supported by the data, politely say so.\n"
            "5) If multiple wines match, recommend 2-3 and briefly explain why.\n"
            "6) Mention wine names exactly as shown in the data (so the UI can match them).\n"
            "7) Order your recommendations by importance: the first wine you recommend "
            "should be the best fit, then the next, etc.\n"
            "8) Vary your phrasing; do not repeatedly start with the same sentence pattern.\n"
            "9) Never name a wine that is not in the Wine context list, even if you know it "
            "from general knowledge.\n"
            "10) If the user asked to skip or avoid a country, do not recommend wines from "
            "that country (the context list will already exclude them)."
        )

        primary_context = self.repository.wines_to_context(primary_wines)
        context_block = self.repository.wines_to_context(wines)
        user_prompt = (
            f"User question: {question}\n\n"
            f"Suggested starting points (you may use others from the full list):\n{primary_context}\n\n"
            f"Wine context:\n{context_block}\n\n"
            "Provide a grounded recommendation. Use exact wine names from the list."
        )

        try:
            llm_response = llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
            answer_text = str(llm_response.content).strip()
            if not answer_text:
                answer_text = fallback_answer(question, primary_wines)
            elif not answer_references_primary_wines(answer_text, primary_wines):
                anchor_names = ", ".join(
                    wine.get("name", "Unknown wine") for wine in primary_wines[:3]
                )
                answer_text = f"Top picks from this catalog are {anchor_names}. {answer_text}"
            if answer_mentions_catalog_bottle_outside_context(answer_text, wines, self.repository):
                answer_text = fallback_answer(question, primary_wines)
        except Exception:
            answer_text = (
                f"{fallback_answer(question, primary_wines)} "
                "I could not reach the local Ollama model at http://localhost:11434."
            )

        wines_ordered = reorder_wines_by_answer(answer_text, wines)
        return AskResponse(answer=answer_text, wines=wines_ordered)
