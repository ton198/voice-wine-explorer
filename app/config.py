import os

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINE_CSV_PATH = os.getenv("WINE_CSV_PATH", os.path.join(PROJECT_ROOT, "wines.csv"))
INDEX_HTML_PATH = os.path.join(PROJECT_ROOT, "index.html")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

MAX_CONTEXT_WINES = 10
MIN_RESULT_WINES = 3

WINE_TERMS = {
    "wine",
    "wines",
    "red",
    "white",
    "rose",
    "rosé",
    "sparkling",
    "cabernet",
    "pinot",
    "merlot",
    "chardonnay",
    "sauvignon",
    "malbec",
    "champagne",
    "prosecco",
    "varietal",
    "vintage",
    "pairing",
    "bottle",
    "recommend",
    "recommendation",
    "pair",
    "food",
    "budget",
    "bottles",
    "housewarming",
    "gift",
}

COLOR_KEYWORDS = {
    "red": "red",
    "white": "white",
    "rose": "rose",
    "rosé": "rose",
    "sparkling": "sparkling",
}

NON_WINE_REPLY = (
    "I can only help with wine recommendations from this catalog. "
    "Ask about wine styles, regions, varietals, ratings, or budget."
)

BUDGET_TERMS = {
    "budget",
    "budget-friendly",
    "budget friendly",
    "affordable",
    "cheap",
    "inexpensive",
    "value",
    "good value",
    "best value",
}

# No rating-based sorts: order is LLM-chosen via plan (catalog / price / name) or CSV order.
ALLOWED_SORT_MODES = {
    "catalog_order",
    "price_asc",
    "price_desc",
    "name_asc",
    "price_near",
    "rating_desc",
}

CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "null",
]
