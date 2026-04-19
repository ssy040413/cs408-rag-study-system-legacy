# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a local-deployment RAG learning assistant for the 408 CS graduate entrance exam (考研计算机专业课). It processes scanned PDF textbooks through an OCR pipeline, builds a semantic vector knowledge base, and provides a chat interface with precise source citation and PDF page jumping.

## Common Commands

### Run Backend
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8001
```

### Run Frontend
```bash
cd frontend
npm install
npm run dev        # Vite dev server on http://localhost:5173
npm run build      # Production build
npm run preview    # Preview production build
```

### Build Knowledge Base
```bash
cd data
python build_kb_with_cloud_ocr.py
```
Requires cloud OCR credentials (Baidu preferred): `BAIDU_OCR_API_KEY` and `BAIDU_OCR_SECRET_KEY`.

## High-Level Architecture

### Backend (`backend/app/`)

**FastAPI service** with the following modules:

- `main.py` — Core FastAPI app. Mounts static files, defines RAG chat stream (`POST /api/chat/stream`), session management, knowledge browser APIs (`/api/kb/chapters`, `/api/kb/chapter_docs`), health check, and LLM settings endpoints.
- `llm_client.py` — Dynamic LLM client management. Loads/saves user config to `data/user_llm_config.json`. Supports both `anthropic` and `openai` providers via a unified `stream_llm()` async generator abstraction. API keys are masked when returned to the frontend.
- `config.py` — Default environment-driven config for ChromaDB path, collection name (`cs408_kb`), and fallback LLM credentials.
- `models.py` — Pydantic models: `ChatRequest`, `KBQueryRequest`, `LLMConfig`.
- `sessions.py` — In-memory `SessionManager` (server-side dict) for multi-turn conversation history.
- `ocr_engine.py` — Abstract OCR engine with implementations for Baidu, Aliyun, and Tencent.

**RAG Flow:**
1. User query → BGE-m3 embedding → ChromaDB ANN retrieval (Top-K)
2. Retrieved chunks + system prompt + last 6 history turns → LLM stream
3. SSE events: `session_id` → `retrieving` → `thinking` → `message` (delta) → `source` (metadata) → `end`

### Frontend (`frontend/src/`)

**Vue 3 SPA** with two routes (`/` for chat, `/kb` for knowledge browser):

- `components/ChatPage.vue` — Main chat UI. Consumes SSE via `fetch()` + `ReadableStream`. Renders Markdown, C code syntax highlighting (highlight.js), and math formulas (KaTeX with custom `$`/`$$` rules). Sources are collapsible with PDF page links.
- `components/KnowledgeBrowser.vue` — TOC tree browser (`el-tree`) showing subject → chapter hierarchy. Clicking a leaf loads chunk cards with calibrated page ranges and "Open PDF" links using `#page=X` hash fragments.
- `components/LLMSettingsDialog.vue` — Dialog to configure provider, base URL, API key, and model. Reads/writes via `GET/POST /api/settings/llm`.
- `router.js` — Two routes: `/` (ChatPage) and `/kb` (KnowledgeBrowser).

**Frontend Constants:**
- `API_BASE = 'http://localhost:8001'` (hardcoded in components)
- `STATIC_BASE = 'http://localhost:8001/static/408'` (for PDF links)

### Data Pipeline (`data/`)

**`build_kb_with_cloud_ocr.py`** orchestrates the full knowledge base construction:
1. **Rasterization** — PyMuPDF renders PDF pages to PNG at 200 DPI.
2. **OCR** — Async cloud OCR with `Semaphore(2)` (Baidu `accurate_basic` preferred). Results cached to `ocr_pages.json` for resumability.
3. **Cleaning** — RegEx filters remove watermarks, ads, and page headers/footers specific to the "竟成" textbook.
4. **TOC Reconstruction** — Parses directory pages with regexes; handles missing spaces and multi-line page numbers via `last_entry` backfill.
5. **Page Offset Calibration** — Samples multiple TOC entries to compute median offset between physical PDF pages and printed book page numbers.
6. **Chunking** — Two-stage process:
   - **Hard split** by TOC tree boundaries (parent nodes only keep content before first child).
   - **Semantic split** for oversized chunks: splits to atomic units by paragraph, embeds adjacent units with BGE-m3, and cuts when cosine similarity drops below `0.72` (indicating topic shift).
7. **Embedding & Storage** — BGE-m3 generates 1024-dim vectors, written to `chroma_db` collection `cs408_kb`.

### Key Directories

- `408/` — Source PDF textbooks.
- `data/chroma_db/` — Persistent ChromaDB vector store.
- `data/user_llm_config.json` — Runtime user LLM configuration (local JSON persistence).

### Environment Variables

Copy `.env.example` to `.env` and fill in:
- `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` — Fallback/default LLM credentials.
- `BAIDU_OCR_API_KEY` / `BAIDU_OCR_SECRET_KEY` — Required for knowledge base building.

### Important Implementation Details

- **Ports:** The frontend hardcodes `API_BASE = 'http://localhost:8001'`, so the backend should run on port `8001` during development (not 8000 as stated in root README).
- **LLM Provider Switching:** Changing provider in settings instantly affects the next chat because `get_llm_client()` is called per-request in `stream_chat()`. No restart is required after saving via the settings dialog.
- **Static PDF Serving:** `app.mount("/static/408", StaticFiles(directory="C:/Users/31314/Desktop/rag/408"), name="static_408")` serves PDFs directly. The frontend generates URLs like `.../DS.pdf#page=125` for native browser PDF jumping.
- **Sessions are ephemeral:** `SessionManager` stores conversation history in a Python dict. Restarting the backend clears all sessions.
