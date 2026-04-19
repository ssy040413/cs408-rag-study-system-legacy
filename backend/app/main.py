import json
import os
from pathlib import Path
from typing import AsyncIterable

import chromadb
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sentence_transformers import SentenceTransformer

from .config import CHROMA_DB_PATH, COLLECTION_NAME, TOP_K
from .models import ChatRequest, KBQueryRequest, LLMConfig
from .sessions import session_mgr
from .llm_client import load_user_config, get_llm_config, save_user_config, get_llm_client, stream_llm

app = FastAPI(title="408考研智能学习系统")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ChromaDB client
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
try:
    collection = chroma_client.get_collection(name=COLLECTION_NAME)
except Exception:
    collection = chroma_client.create_collection(name=COLLECTION_NAME)

# Load user LLM config at startup
load_user_config()

# Embedding model (BGE-m3, 1024-dim)
print("Loading BGE-m3 embedding model...")
embedding_model = SentenceTransformer("BAAI/bge-m3")

# Mount 408 PDF directory for direct browser access
STATIC_408_DIR = str(Path(__file__).resolve().parent.parent.parent / "408")
app.mount("/static/408", StaticFiles(directory=STATIC_408_DIR), name="static_408")

SYSTEM_PROMPT = (
    "你是408考研计算机专业课辅导专家。请严格根据以下参考资料回答问题。"
    "如果资料不足以回答问题，请明确说明。"
    "回答要准确、清晰、有条理，适合考研学生理解。"
    "最后请列出参考来源的简要信息。"
)


def retrieve_docs(query: str, top_k: int = TOP_K):
    embedding = embedding_model.encode([query], normalize_embeddings=True).tolist()
    results = collection.query(
        query_embeddings=embedding,
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    return [{"content": d, "metadata": m} for d, m in zip(docs, metas)]


async def stream_chat(request: ChatRequest):
    session_id = session_mgr.ensure_session(request.session_id or None)

    user_msg = request.message
    session_mgr.add_message(session_id, "user", user_msg)

    # yield session_id first
    yield f"event: session_id\ndata: {json.dumps({'session_id': session_id}, ensure_ascii=False)}\n\n"

    # 1) 通知前端：正在调用 RAG 检索知识库
    yield f"event: retrieving\ndata: {json.dumps({'hint':'正在检索知识库...'}, ensure_ascii=False)}\n\n"

    # RAG retrieval
    docs = retrieve_docs(user_msg, TOP_K)
    context_parts = []
    for i, doc in enumerate(docs, 1):
        meta = doc["metadata"]
        source_info = f"[{i}] {meta.get('subject', '')}-{meta.get('chapter', '')}"
        context_parts.append(f"{source_info}\n{doc['content']}")
    context = "\n\n".join(context_parts)

    # 2) 通知前端：检索完成，正在让 AI 思考/生成
    yield f"event: thinking\ndata: {json.dumps({'hint':'正在分析问题并生成回答...'}, ensure_ascii=False)}\n\n"

    # Anthropic format: system prompt is separate, messages only user/assistant
    anthropic_messages = []
    history = session_mgr.get_session(session_id)[-7:-1]
    for h in history:
        anthropic_messages.append({"role": h["role"], "content": h["content"]})
    anthropic_messages.append({"role": "user", "content": user_msg})

    system_text = f"{SYSTEM_PROMPT}\n\n参考资料：\n{context}"

    client = get_llm_client()
    full_response = ""
    try:
        async for text in stream_llm(
            client=client,
            model=get_llm_config().get("model"),
            system=system_text,
            messages=anthropic_messages,
            temperature=0.3,
            max_tokens=2048,
        ):
            full_response += text
            payload = json.dumps({"delta": text}, ensure_ascii=False)
            yield f"event: message\ndata: {payload}\n\n"
    except Exception as e:
        err_msg = f"\n[模型调用出错: {str(e)}]"
        full_response += err_msg
        payload = json.dumps({"delta": err_msg}, ensure_ascii=False)
        yield f"event: message\ndata: {payload}\n\n"

    # yield sources
    sources = []
    for doc in docs:
        meta = doc["metadata"]
        sources.append({
            "subject": meta.get("subject", ""),
            "chapter": meta.get("chapter", ""),
            "source": meta.get("source", ""),
            "page_start": meta.get("page_start", ""),
            "page_end": meta.get("page_end", ""),
            "content": doc["content"][:300] + "..." if len(doc["content"]) > 300 else doc["content"],
        })
    yield f"event: source\ndata: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"

    # end
    yield f"event: end\ndata: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

    session_mgr.add_message(session_id, "assistant", full_response)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    return StreamingResponse(stream_chat(request), media_type="text/event-stream")


@app.get("/api/sessions")
async def list_sessions():
    sessions = session_mgr.get_all_sessions()
    enriched = []
    for s in sessions:
        msgs = session_mgr.get_session(s["session_id"])
        title = "新对话"
        for m in msgs:
            if m["role"] == "user":
                title = m["content"][:20] + "..." if len(m["content"]) > 20 else m["content"]
                break
        enriched.append({"session_id": s["session_id"], "title": title, "message_count": s["message_count"]})
    return {"sessions": list(reversed(enriched))}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    return {"session_id": session_id, "messages": session_mgr.get_session(session_id)}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    ok = session_mgr.delete_session(session_id)
    return {"success": ok}


@app.post("/api/kb/query")
async def kb_query(request: KBQueryRequest):
    docs = retrieve_docs(request.query, request.top_k or TOP_K)
    return {"query": request.query, "results": docs}


@app.get("/api/kb/chapters")
async def kb_chapters():
    """Return subject/chapter tree for knowledge browser."""
    all_meta = collection.get(include=["metadatas"], limit=20000)
    metas = all_meta.get("metadatas", [])

    # Build subject -> set(chapters)
    subject_map = {}
    for m in metas:
        subject = m.get("subject", "未知科目")
        chapter = m.get("chapter", "")
        if not chapter:
            continue
        # Strip part suffix for grouping
        base_chapter = chapter.split(" (part")[0].strip()
        subject_map.setdefault(subject, set()).add(base_chapter)

    tree = []
    for subject in sorted(subject_map.keys()):
        children = []
        for ch in sorted(subject_map[subject]):
            children.append({
                "label": ch,
                "subject": subject,
                "chapter": ch,
                "is_leaf": True,
            })
        tree.append({
            "label": subject,
            "subject": subject,
            "children": children,
        })
    return {"tree": tree}


@app.get("/api/kb/chapter_docs")
async def kb_chapter_docs(
    subject: str = Query(..., description="Subject name"),
    chapter: str = Query(..., description="Chapter name (base, without part suffix)"),
):
    """Return all chunks belonging to a given subject and chapter."""
    results = collection.get(
        where={"subject": subject},
        include=["documents", "metadatas"],
    )
    docs = []
    documents = results.get("documents", [])
    metadatas = results.get("metadatas", [])
    for doc, meta in zip(documents, metadatas):
        meta_chapter = meta.get("chapter", "")
        base = meta_chapter.split(" (part")[0].strip() if " (part" in meta_chapter else meta_chapter.strip()
        if base != chapter:
            continue
        docs.append({
            "content": doc,
            "chapter": meta_chapter,
            "subject": meta.get("subject", ""),
            "source": meta.get("source", ""),
            "page_start": meta.get("page_start", ""),
            "page_end": meta.get("page_end", ""),
        })
    # Sort by page_start numerically when possible
    docs.sort(key=lambda x: int(x["page_start"]) if str(x["page_start"]).isdigit() else 0)
    return {"docs": docs}


@app.get("/health")
async def health():
    count = collection.count()
    return {"status": "ok", "kb_documents": count}


@app.get("/api/settings/llm")
async def get_llm_settings():
    return get_llm_config(mask_api_key=False)


@app.post("/api/settings/llm")
async def update_llm_settings(config: LLMConfig):
    save_user_config(config.model_dump())
    return {"success": True, "message": "配置已保存"}
