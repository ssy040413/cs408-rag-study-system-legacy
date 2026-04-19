import os
from pathlib import Path

CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", str(Path(__file__).resolve().parent.parent.parent / "data" / "chroma_db"))
COLLECTION_NAME = "cs408_kb"

LLM_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.kimi.com/coding/")
LLM_API_KEY = os.getenv("ANTHROPIC_AUTH_TOKEN", "")
LLM_MODEL = os.getenv("LLM_MODEL", "kimi-for-coding")

TOP_K = 5
