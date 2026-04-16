import json
import re
from typing import Any

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from app.config import (
    ALLOWED_SORT_MODES,
    BUDGET_TERMS,
    COLOR_KEYWORDS,
    MAX_CONTEXT_WINES,
    MIN_RESULT_WINES,
    WINE_TERMS,
)
from app.repository import WineRepository, normalize_text


def extract_around_price_center(question: str) -> float | None:
    """If the user asks for a price ``around/about $N``, return that target amount."""
    q = normalize_text(question)
    m = re.search(
        r"(?:around|about|approximately|roughly)\s*\$?\s*(\d+(?:\.\d+)?)\b",
        q,
    )
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def question_prioritizes_highest_price(question: str) -> bool:
    n = normalize_text(question)
    return bool(
        re.search(
            r"\b(most expensive|priciest|highest[-\s]priced|highest[-\s]price|"
            r"costs?\s+the\s+most|biggest\s+price\s+tag)\b",
            n,
        )
    )


def question_prioritizes_rating_rank(question: str) -> bool:
    n = normalize_text(question)
    return bool(
        re.search(
            r"\b(best[-\s]?rated|highest[-\s]?rated|top[-\s]?rated|"
            r"best\s+rating|highest\s+score|top\s+scores?)\b",
            n,
        )
    )


def extract_price_bounds(question: str) -> tuple[float | None, float | None]:
    """Parse (min_retail, max_retail) from the question.

    A bare ``$N`` is treated as a maximum (budget ceiling) only when no explicit
    floor phrase matched, so ``above $40`` does not become ``<= 40``.

    ``around $40`` yields a symmetric band around 40 (20% or at least $5 each side).
    """
    q = normalize_text(question)
    around_target = extract_around_price_center(question)
    if around_target is not None:
        span = max(5.0, around_target * 0.20)
        return (max(0.0, around_target - span), around_target + span)

    min_price: float | None = None
    max_price: float | None = None

    floor_match = re.search(
        r"(?:above|over|more than|greater than|higher than|at least|minimum|min)\s*\$?\s*(\d+(?:\.\d+)?)\b",
        q,
    )
    if floor_match:
        try:
            min_price = float(floor_match.group(1))
        except ValueError:
            min_price = None

    ceiling_match = re.search(
        r"(?:under|below|less than|up to|maximum|max|cheaper than)\s*\$?\s*(\d+(?:\.\d+)?)\b",
        q,
    )
    if ceiling_match:
        try:
            max_price = float(ceiling_match.group(1))
        except ValueError:
            max_price = None

    if min_price is None and max_price is None:
        bare = re.search(r"\$\s*(\d+(?:\.\d+)?)\b", q)
        if bare:
            try:
                max_price = float(bare.group(1))
            except ValueError:
                max_price = None

    return min_price, max_price


def apply_question_price_to_plan(plan: dict[str, Any], question: str) -> dict[str, Any]:
    """Align plan price filters and sort mode with explicit phrases in the user question.

    When the user states a floor (e.g. ``above $40``) but no ceiling, any
    ``max_price`` from the LLM is dropped so results are not capped at the
    same dollar figure.
    """
    n = normalize_text(question)
    sets_floor = bool(
        re.search(
            r"(?:above|over|more than|greater than|higher than|at least|minimum|min)\s*\$?\s*\d",
            n,
        )
    )
    sets_ceiling = bool(
        re.search(
            r"(?:under|below|less than|up to|maximum|max|cheaper than)\s*\$?\s*\d",
            n,
        )
    )
    bare_ceiling = bool(re.search(r"\$\s*\d", n)) and not sets_floor
    sets_around = bool(
        re.search(r"(?:around|about|approximately|roughly)\s*\$?\s*\d", n)
    )

    q_min, q_max = extract_price_bounds(question)
    out = dict(plan)

    if sets_around:
        out["min_price"], out["max_price"] = q_min, q_max
        out["near_price"] = extract_around_price_center(question)
        out["sort_by"] = "price_near"
        return out

    if question_prioritizes_highest_price(question):
        out["min_price"] = None
        out["near_price"] = None
        if sets_ceiling or bare_ceiling:
            out["max_price"] = q_max
        else:
            out["max_price"] = None
        out["sort_by"] = "price_desc"
        return out

    if sets_floor:
        out["min_price"] = q_min
    if sets_ceiling or bare_ceiling:
        out["max_price"] = q_max
        if not sets_floor:
            out["min_price"] = None
    elif sets_floor:
        out["max_price"] = None
    if sets_floor and not (sets_ceiling or bare_ceiling):
        out["sort_by"] = "price_desc"

    if out.get("sort_by") == "catalog_order":
        qm = normalize_text(question)
        budget_intent = any(term in qm for term in BUDGET_TERMS) or out.get("max_price") is not None
        floor_intent = out.get("min_price") is not None
        if budget_intent and not floor_intent:
            out["sort_by"] = "price_asc"
        elif floor_intent and not budget_intent:
            out["sort_by"] = "price_desc"
        elif budget_intent and floor_intent:
            out["sort_by"] = "price_asc"

    if question_prioritizes_rating_rank(question):
        if out.get("sort_by") not in {"price_desc", "price_near"}:
            out["sort_by"] = "rating_desc"
    return out


def extract_min_price(question: str) -> float | None:
    lo, _hi = extract_price_bounds(question)
    return lo


def extract_max_price(question: str) -> float | None:
    _lo, hi = extract_price_bounds(question)
    return hi


def question_is_wine_related(question: str, repository: WineRepository) -> bool:
    q = normalize_text(question)
    if any(term in q for term in WINE_TERMS):
        return True
    if repository.contains_any_phrase(q, repository.region_values):
        return True
    if repository.contains_any_phrase(q, repository.country_values):
        return True
    if repository.contains_any_phrase(q, repository.varietal_values):
        return True
    if re.search(r"\$\s*\d+|\d+\s*(?:usd|dollars?)", q):
        return True
    if re.search(r"\b(around|about|roughly|approximately)\s*\$?\s*\d+", q):
        return True
    return False


def apply_question_geo_to_plan(
    plan: dict[str, Any], question: str, repository: WineRepository
) -> dict[str, Any]:
    """Merge country exclusions (and conflicting includes) from the user question."""
    _inc_raw, exc_raw = repository.split_country_intent(question)
    if not exc_raw:
        return plan
    out = dict(plan)
    inc = dict(out.get("include") or {})
    ex = dict(out.get("exclude") or {})

    ex_cc = ex.get("countries") or []
    if not isinstance(ex_cc, list):
        ex_cc = []
    merged_names = sorted({normalize_text(c) for c in ex_cc if c} | set(exc_raw))
    ex["countries"] = normalize_country_values(list(merged_names), repository)

    inc_cc = inc.get("countries") or []
    if isinstance(inc_cc, list) and inc_cc:
        exc_set = set(ex["countries"])
        inc["countries"] = [c for c in normalize_country_values(inc_cc, repository) if c not in exc_set]

    inc_regions = inc.get("regions") or []
    if isinstance(inc_regions, list) and inc_regions:
        exc_set = set(exc_raw)
        matched_regions = match_catalog_values(inc_regions, repository.region_values)
        inc["regions"] = [r for r in matched_regions if r not in exc_set]

    out["include"] = inc
    out["exclude"] = ex
    return out


def filter_wines_heuristic(question: str, repository: WineRepository) -> pd.DataFrame:
    filtered = repository.df.copy()
    q = normalize_text(question)

    selected_colors = [value for key, value in COLOR_KEYWORDS.items() if key in q]
    if selected_colors:
        filtered = filtered[filtered["color_normalized"].isin(selected_colors)]

    matched_regions = repository.contains_any_phrase(q, repository.region_values)
    # Catalog may include a region literally named "other"; skip when the user means
    # "any other regions/countries" rather than that appellation.
    if matched_regions and re.search(
        r"\b(?:any|some)\s+other\s+(?:regions?|countries|places)\b", q
    ):
        matched_regions = [m for m in matched_regions if m not in {"other", "other u.s."}]

    matched_countries, excluded_countries = repository.split_country_intent(q)
    # Some rows use the country name as ``Region``; do not treat that as a region filter
    # when the user is excluding that country.
    if excluded_countries and matched_regions:
        exc = set(excluded_countries)
        matched_regions = [m for m in matched_regions if m not in exc]

    if matched_regions:
        filtered = filtered[filtered["region_normalized"].isin(matched_regions)]

    if matched_countries:
        filtered = filtered[filtered["country_normalized"].isin(matched_countries)]
    if excluded_countries:
        filtered = filtered[~filtered["country_normalized"].isin(excluded_countries)]

    matched_varietals = repository.contains_any_phrase(q, repository.varietal_values)
    if matched_varietals:
        filtered = filtered[filtered["varietal_normalized"].isin(matched_varietals)]

    min_price, max_price = extract_price_bounds(question)
    if max_price is not None:
        filtered = filtered[filtered["Retail"] <= max_price]
    if min_price is not None:
        filtered = filtered[filtered["Retail"] >= min_price]

    if filtered.empty:
        return filtered

    near = extract_around_price_center(question)
    if near is not None:
        tmp = filtered.assign(_near=(filtered["Retail"] - near).abs())
        return (
            tmp.sort_values(by=["_near", "Retail", "Name"], ascending=[True, True, True], na_position="last")
            .drop(columns=["_near"])
            .head(MAX_CONTEXT_WINES)
        )

    if question_prioritizes_highest_price(question):
        return filtered.sort_values(
            by=["Retail", "Name"],
            ascending=[False, True],
            na_position="last",
        ).head(MAX_CONTEXT_WINES)

    if question_prioritizes_rating_rank(question):
        return filtered.sort_values(
            by=["best_rating_score", "Retail", "Name"],
            ascending=[False, False, True],
            na_position="last",
        ).head(MAX_CONTEXT_WINES)

    budget_intent = any(term in q for term in BUDGET_TERMS) or max_price is not None
    floor_intent = min_price is not None
    if budget_intent and not floor_intent:
        return filtered.sort_values(
            by=["Retail", "Name"],
            ascending=[True, True],
            na_position="last",
        ).head(MAX_CONTEXT_WINES)
    if floor_intent and not budget_intent:
        return filtered.sort_values(
            by=["Retail", "Name"],
            ascending=[False, True],
            na_position="last",
        ).head(MAX_CONTEXT_WINES)
    if budget_intent and floor_intent:
        return filtered.sort_values(
            by=["Retail", "Name"],
            ascending=[True, True],
            na_position="last",
        ).head(MAX_CONTEXT_WINES)

    # Preserve catalog row order (no rating sort).
    return filtered.head(MAX_CONTEXT_WINES)


def extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None

    fenced_match = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text, re.IGNORECASE)
    if fenced_match:
        try:
            parsed = json.loads(fenced_match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    object_match = re.search(r"\{[\s\S]*\}", text)
    if object_match:
        try:
            parsed = json.loads(object_match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    return None


def match_catalog_values(raw_values: Any, catalog: list[str]) -> list[str]:
    if not isinstance(raw_values, list):
        return []
    matched: set[str] = set()
    for raw in raw_values:
        value = normalize_text(raw)
        if not value:
            continue
        for item in catalog:
            if value == item or value in item or item in value:
                matched.add(item)
    return sorted(matched)


def normalize_color_values(raw_values: Any) -> list[str]:
    if not isinstance(raw_values, list):
        return []
    normalized: set[str] = set()
    for raw in raw_values:
        value = normalize_text(raw)
        if not value:
            continue
        if value in COLOR_KEYWORDS:
            normalized.add(COLOR_KEYWORDS[value])
        elif value in {"rose", "rosé"}:
            normalized.add("rose")
    return sorted(normalized)


def normalize_country_values(raw_values: Any, repository: WineRepository) -> list[str]:
    if not isinstance(raw_values, list):
        return []
    normalized: set[str] = set()
    for raw in raw_values:
        value = normalize_text(raw)
        if not value:
            continue
        if value in repository.country_aliases:
            normalized.add(repository.country_aliases[value])
            continue
        for country in repository.country_values:
            if value == country or value in country or country in value:
                normalized.add(country)
    return sorted(normalized)


def default_query_plan(question: str, repository: WineRepository) -> dict[str, Any]:
    return apply_question_price_to_plan(
        {
            "is_wine_related": question_is_wine_related(question, repository),
            "needs_clarification": False,
            "clarification_question": "",
            "include": {"colors": [], "countries": [], "regions": [], "varietals": []},
            "exclude": {"colors": [], "countries": [], "regions": [], "varietals": []},
            "min_price": None,
            "max_price": None,
            "near_price": None,
            "sort_by": "catalog_order",
            "limit": MAX_CONTEXT_WINES,
        },
        question,
    )


def generate_query_plan(
    question: str, repository: WineRepository, llm: Any
) -> dict[str, Any] | None:
    system_prompt = (
        "You are a query planner for a wine search backend. "
        "Return ONLY a valid JSON object with no extra text.\n\n"
        "Schema:\n"
        "{\n"
        '  "is_wine_related": boolean,\n'
        '  "needs_clarification": boolean,\n'
        '  "clarification_question": string,\n'
        '  "include": {"colors": [string], "countries": [string], "regions": [string], "varietals": [string]},\n'
        '  "exclude": {"colors": [string], "countries": [string], "regions": [string], "varietals": [string]},\n'
        '  "min_price": number|null,\n'
        '  "max_price": number|null,\n'
        '  "near_price": number|null,\n'
        '  "sort_by": "catalog_order"|"price_asc"|"price_desc"|"name_asc"|"price_near"|"rating_desc",\n'
        '  "limit": number\n'
        "}\n\n"
        "Guidance:\n"
        "- Choose sort_by to match user intent.\n"
        "- catalog_order: keep stable catalog order after filters (default for broad asks).\n"
        "- price_asc / price_desc: when user cares about cheap/expensive or budget.\n"
        "- price_near + near_price: when user says around/about $X (symmetric band is applied separately).\n"
        "- rating_desc: when user asks for best/highest/top rated wines.\n"
        "- name_asc: when alphabetical order helps.\n"
        "- min_price for phrases like above/over/more than/at least $X; max_price for under/below/up to $X.\n"
        "- Put negations (e.g., not from US, hate Italy, avoid French wines) into exclude.countries.\n"
        "- If non-wine topic, set is_wine_related=false."
    )

    try:
        response = llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"User question: {question}"),
            ]
        )
    except Exception:
        return None

    plan_raw = extract_json_object(str(response.content))
    if not plan_raw:
        return None

    include = plan_raw.get("include") or {}
    if not isinstance(include, dict):
        include = {}
    exclude = plan_raw.get("exclude") or {}
    if not isinstance(exclude, dict):
        exclude = {}

    sort_by = normalize_text(plan_raw.get("sort_by", "catalog_order"))
    legacy = {"balanced"}
    if sort_by in legacy or sort_by not in ALLOWED_SORT_MODES:
        sort_by = "catalog_order"

    try:
        limit = int(plan_raw.get("limit", MAX_CONTEXT_WINES))
    except (ValueError, TypeError):
        limit = MAX_CONTEXT_WINES
    limit = max(MIN_RESULT_WINES, min(MAX_CONTEXT_WINES, limit))

    min_price: float | None
    try:
        raw_min = plan_raw.get("min_price")
        min_price = float(raw_min) if raw_min is not None else None
    except (TypeError, ValueError):
        min_price = None

    max_price: float | None
    try:
        raw_price = plan_raw.get("max_price")
        max_price = float(raw_price) if raw_price is not None else None
    except (TypeError, ValueError):
        max_price = None

    near_price: float | None
    try:
        raw_near = plan_raw.get("near_price")
        near_price = float(raw_near) if raw_near is not None else None
    except (TypeError, ValueError):
        near_price = None

    clarification_raw = plan_raw.get("clarification_question", "")
    clarification_text = str(clarification_raw).strip()
    if normalize_text(clarification_text) in {"none", "null", "n/a", "na"}:
        clarification_text = ""

    return {
        "is_wine_related": bool(plan_raw.get("is_wine_related", True)),
        "needs_clarification": bool(plan_raw.get("needs_clarification", False)),
        "clarification_question": clarification_text,
        "include": {
            "colors": normalize_color_values(include.get("colors", [])),
            "countries": normalize_country_values(include.get("countries", []), repository),
            "regions": match_catalog_values(include.get("regions", []), repository.region_values),
            "varietals": match_catalog_values(
                include.get("varietals", []), repository.varietal_values
            ),
        },
        "exclude": {
            "colors": normalize_color_values(exclude.get("colors", [])),
            "countries": normalize_country_values(exclude.get("countries", []), repository),
            "regions": match_catalog_values(exclude.get("regions", []), repository.region_values),
            "varietals": match_catalog_values(
                exclude.get("varietals", []), repository.varietal_values
            ),
        },
        "min_price": min_price,
        "max_price": max_price,
        "near_price": near_price,
        "sort_by": sort_by,
        "limit": limit,
    }


def filter_wines_with_plan(plan: dict[str, Any], repository: WineRepository) -> pd.DataFrame:
    filtered = repository.df.copy()
    include = plan.get("include", {})
    exclude = plan.get("exclude", {})
    if not isinstance(include, dict):
        include = {}
    if not isinstance(exclude, dict):
        exclude = {}

    include_colors = include.get("colors", [])
    exclude_colors = exclude.get("colors", [])
    if include_colors:
        filtered = filtered[filtered["color_normalized"].isin(include_colors)]
    if exclude_colors:
        filtered = filtered[~filtered["color_normalized"].isin(exclude_colors)]

    include_regions = include.get("regions", []) or []
    exclude_regions = exclude.get("regions", []) or []
    include_countries = include.get("countries", []) or []
    exclude_countries = exclude.get("countries", []) or []
    if isinstance(include_regions, list) and exclude_countries:
        exc = set(exclude_countries)
        include_regions = [r for r in include_regions if r not in exc]
    if include_regions:
        filtered = filtered[filtered["region_normalized"].isin(include_regions)]
    if exclude_regions:
        filtered = filtered[~filtered["region_normalized"].isin(exclude_regions)]
    if include_countries:
        filtered = filtered[filtered["country_normalized"].isin(include_countries)]
    if exclude_countries:
        filtered = filtered[~filtered["country_normalized"].isin(exclude_countries)]

    include_varietals = include.get("varietals", [])
    exclude_varietals = exclude.get("varietals", [])
    if include_varietals:
        filtered = filtered[filtered["varietal_normalized"].isin(include_varietals)]
    if exclude_varietals:
        filtered = filtered[~filtered["varietal_normalized"].isin(exclude_varietals)]

    min_price = plan.get("min_price")
    if isinstance(min_price, (int, float)):
        filtered = filtered[filtered["Retail"] >= min_price]

    max_price = plan.get("max_price")
    if isinstance(max_price, (int, float)):
        filtered = filtered[filtered["Retail"] <= max_price]

    if filtered.empty:
        return filtered

    sort_by = normalize_text(plan.get("sort_by", "catalog_order"))
    if sort_by not in ALLOWED_SORT_MODES:
        sort_by = "catalog_order"
    if sort_by == "price_asc":
        sorted_df = filtered.sort_values(
            by=["Retail", "Name"], ascending=[True, True], na_position="last"
        )
    elif sort_by == "price_desc":
        sorted_df = filtered.sort_values(
            by=["Retail", "Name"], ascending=[False, True], na_position="last"
        )
    elif sort_by == "name_asc":
        sorted_df = filtered.sort_values(by=["Name"], ascending=[True], na_position="last")
    elif sort_by == "rating_desc":
        sorted_df = filtered.sort_values(
            by=["best_rating_score", "Retail", "Name"],
            ascending=[False, False, True],
            na_position="last",
        )
    elif sort_by == "price_near":
        near = plan.get("near_price")
        if isinstance(near, (int, float)):
            tmp = filtered.assign(_near=(filtered["Retail"] - float(near)).abs())
            sorted_df = tmp.sort_values(
                by=["_near", "Retail", "Name"],
                ascending=[True, True, True],
                na_position="last",
            ).drop(columns=["_near"])
        else:
            sorted_df = filtered
    else:
        # catalog_order: preserve row order from the loaded CSV (no rating sort).
        sorted_df = filtered

    try:
        limit = int(plan.get("limit", MAX_CONTEXT_WINES))
    except (ValueError, TypeError):
        limit = MAX_CONTEXT_WINES
    limit = max(MIN_RESULT_WINES, min(MAX_CONTEXT_WINES, limit))
    return sorted_df.head(limit)
