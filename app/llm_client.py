from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.config import LLM_PROVIDER, OLLAMA_BASE_URL, OLLAMA_MODEL, OPENAI_API_KEY, OPENAI_MODEL


def get_llm():
    if LLM_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is not set. Add it to your .env file."
            )
        return ChatOpenAI(
            model=OPENAI_MODEL,
            api_key=SecretStr(OPENAI_API_KEY),
            temperature=0.35,
        )

    if LLM_PROVIDER == "ollama":
        return ChatOllama(
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            temperature=0.35,
        )

    raise ValueError(
        f"Unsupported LLM provider '{LLM_PROVIDER}'. "
        "Set LLM_PROVIDER=openai or LLM_PROVIDER=ollama in your .env file."
    )
