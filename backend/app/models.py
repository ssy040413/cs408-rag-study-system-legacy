from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class KBQueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = 5


class LLMConfig(BaseModel):
    provider: str
    base_url: str
    api_key: str
    model: str


