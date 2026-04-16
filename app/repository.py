import json
import re
from typing import Any

import pandas as pd

from app.config import WINE_CSV_PATH


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def parse_ratings(raw_value: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return []
    try:
        parsed = json.loads(raw_value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _country_alias_mentioned_negatively(q: str, alias: str) -> bool:
    """True when the user is clearly rejecting wines from this country/adjective."""
    if len(alias) < 2:
        return False
    al = re.escape(alias)
    neg_verbs = (
        r"hate|dislike|loathe|despise|detest|abhor|avoid|skip|shun|eschew|"
        r"can't\s+stand|cannot\s+stand|do\s+not\s+want|don't\s+want|"
        r"not\s+a\s+f(?:an)?\s+of|not\s+into|never\s+want|no\s+more"
    )
    patterns = [
        rf"\b(?:[\w']+\s+){{0,15}}?(?:{neg_verbs})\s+(?:[\w']+\s+){{0,8}}?\b{al}\b",
        rf"\b{al}\b\s*[,:]?\s*(?:sucks|stinks|gross|awful|terrible|the\s+worst)\b",
        rf"\b(?:no|not|never)\s+(?:more\s+)?{al}\b",
        rf"\b(?:anything|something)\s+other\s+than\s+{al}\b",
        rf"\b(?:rather|prefer)\s+not\s+(?:to\s+)?(?:have|drink|get)\s+(?:[\w']+\s+){{0,4}}?{al}\b",
        rf"\b(?:stay|staying)\s+away\s+from\s+{al}\b",
        rf"\b(?:keep|get)\s+(?:me\s+)?away\s+from\s+{al}\b",
        rf"\b(?:not\s+from|outside|excluding|except|non)\s+(?:the\s+)?{al}\b",
        rf"\b{al}\s+excluded\b",
    ]
    return any(re.search(p, q) for p in patterns)


def _country_alias_mentioned_positively(q: str, alias: str) -> bool:
    """True when the user is asking for wines tied to this country/adjective."""
    if len(alias) < 2:
        return False
    al = re.escape(alias)
    patterns = [
        rf"\b(?:from|in|of)\s+[\w\s,]+?\b{al}\b",
        rf"\b{al}\b\s+(?:wines?|reds?|whites?|bottles?|vineyards?|producers?|regions?|sparkling)\b",
        rf"\b(?:love|enjoy|prefer|want|wants|show|recommend|suggest|like|try|only)\w*\s+(?:[\w']+\s+){{0,8}}?\b{al}\b",
    ]
    return any(re.search(p, q) for p in patterns)


def best_rating(ratings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not ratings:
        return None
    scored = [
        rating
        for rating in ratings
        if isinstance(rating, dict)
        and isinstance(rating.get("score"), (int, float))
        and isinstance(rating.get("max_score"), (int, float))
        and rating.get("max_score")
    ]
    if not scored:
        return None
    return max(scored, key=lambda item: item["score"] / item["max_score"])


class WineRepository:
    def __init__(self) -> None:
        self.df: pd.DataFrame = pd.DataFrame()
        self.region_values: list[str] = []
        self.country_values: list[str] = []
        self.varietal_values: list[str] = []
        self.country_aliases: dict[str, str] = {}

    def load(self) -> None:
        df = pd.read_csv(WINE_CSV_PATH)
        df["Retail"] = pd.to_numeric(df["Retail"], errors="coerce")
        df["ratings_list"] = df["professional_ratings"].apply(parse_ratings)
        df["best_rating"] = df["ratings_list"].apply(best_rating)
        df["best_rating_score"] = df["best_rating"].apply(
            lambda x: x.get("score") if isinstance(x, dict) else None
        )

        df["color_normalized"] = df["color"].map(normalize_text)
        df["region_normalized"] = df["Region"].map(normalize_text)
        df["country_normalized"] = df["Country"].map(normalize_text)
        df["varietal_normalized"] = df["Varietal"].map(normalize_text)
        self.df = df

        self.region_values = sorted(
            {
                value
                for value in df["region_normalized"].dropna().tolist()
                if value and len(value) > 2
            }
        )
        self.country_values = sorted(
            {
                value
                for value in df["country_normalized"].dropna().tolist()
                if value and len(value) > 2
            }
        )
        self.varietal_values = sorted(
            {
                value
                for value in df["varietal_normalized"].dropna().tolist()
                if value and len(value) > 2
            }
        )

        self.country_aliases = {country: country for country in self.country_values}
        if "united states" in self.country_aliases:
            self.country_aliases.update(
                {
                    "us": "united states",
                    "u.s.": "united states",
                    "u.s": "united states",
                    "usa": "united states",
                    "america": "united states",
                    "united states of america": "united states",
                }
            )

        demonym_to_country = {
            "italian": "italy",
            "french": "france",
            "spanish": "spain",
            "german": "germany",
            "portuguese": "portugal",
            "argentinian": "argentina",
            "australian": "australia",
            "chilean": "chile",
            "canadian": "canada",
            "israeli": "israel",
            "lebanese": "lebanon",
            "vietnamese": "vietnam",
            "south african": "south africa",
        }
        for demonym, canonical in demonym_to_country.items():
            if canonical in self.country_values:
                self.country_aliases[demonym] = canonical

    def is_loaded(self) -> bool:
        return not self.df.empty

    def contains_any_phrase(self, question: str, phrases: list[str]) -> list[str]:
        q = normalize_text(question)
        matches = []
        for phrase in phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", q):
                matches.append(phrase)
        return matches

    def split_country_intent(self, question: str) -> tuple[list[str], list[str]]:
        q = normalize_text(question)
        include_countries: set[str] = set()
        exclude_countries: set[str] = set()

        for alias, canonical in self.country_aliases.items():
            if len(alias) < 2:
                continue
            if not re.search(rf"\b{re.escape(alias)}\b", q):
                continue

            if _country_alias_mentioned_negatively(q, alias):
                exclude_countries.add(canonical)
                continue
            if _country_alias_mentioned_positively(q, alias):
                include_countries.add(canonical)
                continue

            legacy_negative = [
                rf"(?:not\s+from|outside|excluding|except|non)\s+(?:the\s+)?{re.escape(alias)}\b",
                rf"\b{re.escape(alias)}\s+excluded\b",
            ]
            if any(re.search(pattern, q) for pattern in legacy_negative):
                exclude_countries.add(canonical)
                continue

            # Bare country mention (e.g. catalog-style "France, Italy") → soft include.
            include_countries.add(canonical)

        return sorted(include_countries), sorted(exclude_countries)

    def wines_to_cards(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        wines: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            rating = row.get("best_rating") or {}
            wines.append(
                {
                    "name": row.get("Name", ""),
                    "producer": row.get("Producer", ""),
                    "region": row.get("Region", ""),
                    "country": row.get("Country", ""),
                    "varietal": row.get("Varietal", ""),
                    "vintage": row.get("Vintage", ""),
                    "color": row.get("color", ""),
                    "price": row.get("Retail", None),
                    "image_url": row.get("image_url", ""),
                    "reference_url": row.get("reference_url", ""),
                    "best_rating": rating,
                    "professional_ratings": row.get("ratings_list", []),
                }
            )
        return wines

    def wines_to_context(self, wines: list[dict[str, Any]]) -> str:
        lines = []
        for idx, wine in enumerate(wines, start=1):
            rating = wine.get("best_rating") or {}
            rating_text = ""
            if (
                rating.get("score") is not None
                and rating.get("max_score") is not None
            ):
                rating_text = (
                    f"{rating.get('score')}/{rating.get('max_score')} "
                    f"from {rating.get('source', 'unknown')}"
                )
            line = (
                f"{idx}. {wine.get('name')} ({wine.get('color')}, {wine.get('varietal')}), "
                f"{wine.get('region')}, {wine.get('country')}, "
                f"${wine.get('price')}, best rating: {rating_text or 'n/a'}."
            )
            lines.append(line)
        return "\n".join(lines)
