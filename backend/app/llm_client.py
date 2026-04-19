import json
from pathlib import Path
from typing import AsyncIterable, Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from .config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

USER_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "user_llm_config.json"

_current_config = {
    "provider": "anthropic",
    "base_url": LLM_BASE_URL,
    "api_key": LLM_API_KEY,
    "model": LLM_MODEL,
}


def load_user_config():
    global _current_config
    if USER_CONFIG_PATH.exists():
        try:
            with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                # Only update keys that are present and non-empty
                for k, v in saved.items():
                    if v is not None and v != "":
                        _current_config[k] = v
        except Exception:
            pass


def save_user_config(config: dict):
    global _current_config
    for k, v in config.items():
        if v is not None:
            _current_config[k] = v
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(_current_config, f, ensure_ascii=False, indent=2)


def get_llm_config(mask_api_key: bool = False):
    cfg = _current_config.copy()
    if mask_api_key and cfg.get("api_key"):
        key = cfg["api_key"]
        if len(key) > 8:
            cfg["api_key"] = key[:4] + "****" + key[-4:]
        else:
            cfg["api_key"] = "****"
    return cfg


_client_cache = None
_client_cache_key = None


def get_llm_client():
    global _client_cache, _client_cache_key
    cfg = get_llm_config(mask_api_key=False)
    provider = cfg.get("provider", "anthropic")
    cache_key = (provider, cfg.get("base_url"), cfg.get("api_key"))
    if _client_cache is not None and _client_cache_key == cache_key:
        return _client_cache
    if provider == "openai":
        _client_cache = AsyncOpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
    else:
        _client_cache = AsyncAnthropic(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            default_headers={"User-Agent": "Claude-Code/1.0"},
        )
    _client_cache_key = cache_key
    return _client_cache


async def stream_llm(
    client,
    model: str,
    system: str,
    messages: list,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> AsyncIterable[str]:
    provider = _current_config.get("provider", "anthropic")
    if provider == "openai":
        openai_messages = [{"role": "system", "content": system}]
        for m in messages:
            openai_messages.append({"role": m["role"], "content": m["content"]})
        stream = await client.chat.completions.create(
            model=model,
            messages=openai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    else:
        async with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            temperature=temperature,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text
