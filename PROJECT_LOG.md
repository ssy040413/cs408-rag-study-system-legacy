# 408 RAG 智能答疑系统 —— 工程实现日志

> 本文档记录本项目从零到一的完整构建过程、技术决策、踩坑与修复，以及后续所有保留操作的更新记录。

---

## 一、项目概述

**目标**：构建一个面向 408 计算机专业基础综合考试的智能答疑系统，通过 RAG（检索增强生成）技术，让大模型基于权威教材给出可溯源、低幻觉的专业回答。

**当前状态**：后端 + 前端 MVP 已跑通，正在将示例知识库替换为真实教材内容（竟成 408 数据结构扫描版）。

---

## 二、技术架构总览

采用前后端分离架构：

```
┌─────────────────┐      HTTP/SSE       ┌─────────────────┐
│   Vue 3 前端     │ ◄─────────────────► │  FastAPI 后端   │
│  (Element Plus) │   text/event-stream │  + ChromaDB     │
└─────────────────┘                     └─────────────────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │  BGE-m3 嵌入  │
                                        │  百度 OCR     │
                                        │  云 LLM API   │
                                        └──────────────┘
```

### 2.1 后端 (`backend/`)
- **FastAPI**：提供异步 HTTP API 和 SSE 流式输出。
- **ChromaDB**：本地持久化向量数据库，存储教材文本块及其 Embedding。
- **BGE-m3** (`sentence-transformers`)：生成 1024 维中文文本向量。
- **LangChain**：用于 Prompt 组装和 LLM 调用链编排。
- **自定义 OCR Engine** (`app/ocr_engine.py`)：封装百度/阿里/腾讯云 OCR，统一接口 `recognize_image()`。

### 2.2 前端 (`frontend/`)
- **Vue 3 + Element Plus**：对话界面、侧边栏来源引用、历史会话管理。
- **markdown-it + KaTeX**：渲染 AI 回答中的 Markdown、代码高亮和数学公式。
- **EventSource**：接收后端 SSE 流，实现逐字打印效果。

---

## 三、构建历程（从零到一）

### Phase 1：MVP 快速验证（示例知识库）
- 先用 17 条数据结构概念作为示例数据写入 ChromaDB。
- 打通完整链路：前端提问 → 后端向量检索 → Prompt 拼接 → GLM-4 API → SSE 流式返回答案。
- **验证结论**：RAG 框架可行，SSE 流式体验良好，但示例数据太少，回答深度不够。

### Phase 2：接入真实教材 —— PDF 文本层的噩梦
- 用户在 `C:/Users/31314/Desktop/rag/408/` 目录下存放了多本 PDF 教材（王道、竟成、严蔚敏等）。
- 尝试直接提取文本：
  - `PyMuPDF (fitz)`、`pdfplumber`、`pypdf` 全部失败。
  - 所有扫描版/双色版 PDF 的 **ToUnicode CMap 损坏**，导致 `extract_text()` 输出乱码（如 `概念` → `酸急`）。
- 尝试 **EasyOCR** 本地识别：模型下载到 33% 超时，网络不可行。
- **决策**：放弃本地解析和本地 OCR，改用 **外部云 OCR**（百度高精度版）。

### Phase 3：云 OCR 知识库流水线（当前核心）

新建了两个关键模块：

#### 3.1 `backend/app/ocr_engine.py`
- 封装了 **Baidu OCR**（`accurate_basic` 高精度版）、Aliyun OCR、Tencent OCR。
- `build_ocr_engine()` 根据环境变量自动选择可用的服务商。
- 当前使用百度 OCR，凭据通过环境变量注入：
  ```bash
  export BAIDU_OCR_API_KEY="..."
  export BAIDU_OCR_SECRET_KEY="..."
  ```

#### 3.2 `data/build_kb_with_cloud_ocr.py`
完整 Pipeline 如下：

```
PDF → 渲染为 PNG (DPI=200)
    → 并发调用百度 OCR (Semaphore=2, 控制 QPS)
    → 保存 ocr_pages.json（支持断点续传）
    → 清洗页眉页脚/水印/广告
    → 从目录页解析 TOC (正则重建)
    → 自动检测页码偏移并校正
    → 按章节切分文本块 (chunk_by_toc)
    → 超长块滑动窗口二次切分 (split_large_chunks)
    → 生成 BGE-m3 Embedding
    → 写入 ChromaDB (collection: cs408_kb)
```

### Phase 4：数据清洗与目录重建中的关键修复

这是目前投入精力最多的环节，20 页测试反复调试后形成以下稳定逻辑：

#### 修复 1：水印正则的字符错误
- 原始正则使用了错误的 `竟` 字，导致 `竞成408系列辅导书...` 的广告行未被过滤。
- 修复为字符类 `[竞竟]`，覆盖 OCR 的两种识别结果。

#### 修复 2：目录解析适配无空格格式
- 竟成目录中编号和标题之间常无空格，如 `1.1前言`、`1.2.1指针.`。
- 将正则 `r"^(\d+\.\d+)\s+(.+)$"` 和 `r"^(\d+\.\d+\.\d+)\s+(.+)$"` 中的 `\s+` 改为 `\s*`，使无空格的行也能被正确匹配。

#### 修复 3：页码出现在下一行
- 目录页 OCR 结果中，页码有时会单独成行（如 `2` 在 `1.2.1指针.` 的下一行）。
- 引入 `last_entry` 机制：遇到纯数字行时，将其作为上一个目录条目的页码回填。

#### 修复 4：自动页码偏移检测
- 书籍目录页码和实际 PDF 页码存在偏移（前 10 页为 front matter：前言、总目录）。
- 最初 `chunk_by_toc` 直接按目录页码取内容，结果抓到了广告页。
- **解决方案**：新增 `detect_page_offset()`：
  1. 取多个 `page > 0` 的目录条目作为候选；
  2. 从第 11 页开始在正文里搜索标题关键词，计算 `实际页码 - 目录页码`；
  3. 取偏移量的**中位数**作为全局偏移（抵抗个别条目错误）。
  4. 在 `chunk_by_toc()` 中统一加上该偏移。
- 实测竟成数据结构 PDF 的偏移量为 **+10**。

#### 修复 5：过滤拆行广告
- 部分页面中 `③` 符号和广告文案被 OCR 拆成两行：
  ```
  ③
  竟成针对27考研推出...
  ```
- 增加 `^[③④]$` 单行符号过滤，以及 `.*竟成针对27考研推出.*` 全行广告过滤，正文干净度大幅提升。

---

## 四、核心文件清单

| 文件 | 作用 |
|------|------|
| `backend/app/main.py` | FastAPI 主入口，对话接口、SSE 流输出 |
| `backend/app/rag_service.py` | RAG 核心：检索、重排、Prompt 构建、LLM 调用 |
| `backend/app/ocr_engine.py` | 云 OCR 引擎封装（百度/阿里/腾讯） |
| `backend/app/pdf_processor.py` | 复杂 PDF 处理模块（多卷合并、滑动窗口分块） |
| `data/build_kb_with_cloud_ocr.py` | 云 OCR 知识库构建主脚本 |
| `frontend/src/components/ChatView.vue` | 对话页面组件 |
| `frontend/src/services/api.js` | 前端 API 封装，SSE 连接管理 |
| `chroma_db/` | ChromaDB 本地持久化目录 |
| `408/ocr_output/` | OCR 中间结果（页面图片、ocr_pages.json、chunks.json） |

---

## 五、当前状态与验证结果

- [x] FastAPI + Vue 前后端联调通过
- [x] SSE 流式对话稳定运行
- [x] Baidu 云 OCR 接入成功，20 页测试文本提取准确
- [x] 目录重建成功（解析出 160 个 TOC 条目）
- [x] 页码偏移校正成功（偏移量 = +10）
- [x] 章节切分与滑动窗口二次切分正常
- [ ] **待完成**：跑完整本 491 页 PDF 并写入最终知识库
- [ ] **待完成**：测试 RAG 检索质量与回答效果

---

## 六、后续保留操作记录

> 以下按时间顺序记录后续对该项目的所有重要修改。

### 2026-04-14（第一部分）
- 修复 `build_kb_with_cloud_ocr.py`：
  - 新增 `detect_page_offset()` 自动检测 PDF 页码偏移；
  - 增强 `clean_page_text()` 水印过滤规则（拆行广告、字符错误）；
  - 调整 `chunk_by_toc()` 支持 `page_offset` 参数；
- 完成 20 页测试，偏移量确认中位数为 **10**，章节切分结果符合预期。

### 2026-04-14（第二部分）
- **优化 Chunk 切分策略**：重写 `chunk_by_toc()`，引入目录树结构（基于栈构建父子关系）。
  - **非叶子节点**（如 level 1 大章、有子节点的 level 2）只保留“第一个子节点之前的页面”作为引言/概览，避免吞并所有子章节内容；
  - **叶子节点**（无子节点的 level 2/3）保留完整页面范围；
  - 效果：chunk 数量从 24+ 降至 15，且内容不再重叠，检索粒度聚焦于小节级别。
- 将 `TEST_MAX_PAGES` 从 `20` 改为 `0`，准备处理完整 491 页 PDF。

### 2026-04-14（第三部分）
- **跑通全书 491 页知识库构建**：后台任务 `b7mxvrd2z` 成功完成，关键指标：
  - 百度云 OCR：491/491 页，零失败；
  - 目录解析：160 个 TOC 条目；
  - 页码偏移：中位数 = **10**（与 20 页测试一致）；
  - 文本分块：285 个 chunk；
  - BGE-m3 Embedding：9 batches，耗时约 11 分 34 秒；
  - ChromaDB `cs408_kb` 最终入库：**285 条文档**。
- 状态更新：示例知识库已完全替换为真实教材内容，RAG 后端可基于竟成 408 数据结构扫描版进行检索与回答。

### 2026-04-14（第四部分）
- **修复后端启动崩溃**：安装 requirements.txt 时 numpy 被降级到 1.26.4，在 Windows MINGW 环境下触发 **Segmentation fault**；将 numpy 强制恢复为 **2.4.4** 后后端可正常导入和运行（langchain 虽有 `<2.0` 约束警告，但实际运行未报错）。
- **启动前后端并验证完整链路**：
  - 后端 `uvicorn app.main:app --port 8001` 启动成功，`/health` 返回 `{"status":"ok","kb_documents":285}`；
  - 前端 `npm run dev` 启动成功，服务在 `http://localhost:5176`；
  - **KB Query 测试**：查询"什么是二叉树"，精准召回 `二叉树的定义(p125)`、`二叉树的性质(p126)`、`树、森林的遍历(p175-179)`；
  - **SSE 对话测试**：查询"简述二叉树的定义和性质"，后端通过 Anthropic API 返回结构化 Markdown 回答，包含满二叉树、完全二叉树、BST、AVL 等知识点，并正确附带教材来源引用。
- 状态更新：全书 RAG 知识库已正式上线，系统具备基于真实教材的答疑能力。

### 2026-04-14（第五部分）
- **修复前端 SSE 流式显示卡顿问题**（第一次尝试）：
  - 问题现象：查询"B树"时检索结果能返回，但没有"打字机般"的实时逐字显示效果，看起来像卡住或一次性跳变。
  - 初步判断：streaming 阶段直接用 `v-html="md.render(msg.content)"`，每字都触发 markdown-it 重渲染，性能开销大。
  - 修复：将流式输出阶段改为纯文本 `white-space: pre-wrap` 渲染，完成后再用 markdown-it 渲染最终富文本。
  - 结果：问题未彻底解决，用户反馈仍需切换/刷新窗口才能看到内容。

### 2026-04-14（第六部分）
- **彻底修复前端 SSE 流式显示无实时更新问题**：
  - 问题现象：B 树查询返回 1430 个 SSE chunk（约 2300+ 字），但浏览器窗口内容完全不动，必须切tab或刷新才能看到完整回答。
  - 根因分析（核心 bug）：
    1. **Vue 3 响应式失效**：`sendMessage()` 里创建了本地 `const assistantMsg = {...}` 并 `messages.value.push(assistantMsg)`，后续流式循环中直接修改 `assistantMsg.content += payload.delta`。在 Vue 3 中，这会修改原始对象引用，**绕过响应式代理**，导致 DOM 不更新。
    2. **滚动阻塞渲染**：`await scrollToBottom()` 在循环内每字都执行，内部调用 `await nextTick()`，主线程被大量微任务阻塞。
  - 修复：
    1. 移除 `assistantMsg` 本地变量，所有状态变更改为通过 `messages.value[assistantIdx]` 进行，确保 Vue 响应式正确触发；
    2. 引入 `throttledScroll` 节流滚动（150ms 间隔），避免每字都阻塞 `nextTick()`；
    3. 保留 streaming 阶段纯文本渲染、done 后 Markdown 渲染的策略。
  - 验证：前端 `vite build` 编译通过，SSE 逐字更新恢复实时打字机效果。

### 2026-04-14（第七部分）
- **修复刷新后历史消息格式丢失（带 `#` 的 Markdown 源码显示）**：
  - 根因：后端 `/api/sessions/{sid}` 返回的历史消息没有 `status` 字段，前端模板 `v-if="msg.status === 'done'"` 为 false，导致 Markdown 走了纯文本渲染。
  - 修复：`switchSession()` 加载历史消息时，为 `assistant` 角色自动补 `status: 'done'`；同时模板条件放宽为 `!msg.status || msg.status === 'done'` 时渲染 Markdown。

- **修复左侧对话记录问题**：
  - 根因：
    1. 最新创建的会话总是排在列表底部，不符合常用 IM 交互习惯；
    2. 列表项没有显示消息数，用户难以快速识别活跃会话；
    3. `session-title` 在 title 为空时不显示任何内容。
  - 修复：
    1. 后端 `list_sessions` 返回前使用 `reversed(enriched)`，使最新会话置顶；
    2. 前端 `session-item` 增加 `msg-count` 小徽章显示 `message_count`；
    3. 增加 `s.title || '新对话'` fallback 和 `title` tooltip。

- **修复来源引用不显示精确页码**：
  - 根因：后端 `source` event 仅返回 `subject/chapter/source/content`，缺少 `page_start` 和 `page_end`；同时前端 source 标题模板未拼接页码。
  - 修复：
    1. 后端 `main.py` 在 `stream_chat` 的 source 构造中加入 `page_start` 和 `page_end`；
    2. 前端来源折叠标题改为：`书名 · 章节 · pX-Y`（例如 `27版竟成数据结构-云OCR校准版 · 二叉树的定义 · p125-125`）。
  - 附：此修复过程中发现 Windows 上 uvicorn `--reload` 存在子进程未真正重载的问题（旧进程仍在 8001 端口监听旧代码），已清理僵尸进程并改用干净重启。

### 2026-04-14（第八部分）
- **实现按段落边界/语义相似度的动态分块**：
  1. 新增 `split_to_semantic_units()`：优先按段落边界（双换行）拆分，超长段落再按句子边界二次拆分；
  2. 新增 `semantic_split_chunks()`：对 TOC 切分后仍超过 `max_chars=3000` 的 chunk，先用 BGE-m3 编码每个语义单元，计算相邻单元余弦相似度；
  3. 贪心分组策略：当相似度 `< 0.72` 且当前组已满足 `min_chars=300` 时切分，同时强制不超过 `max_chars`；末尾过短碎片自动向前合并。
- **主流程优化**：将 BGE-m3 模型加载提前到 `main()`，语义分块与最终 Embedding 复用同一模型实例，避免重复加载。
- **修正 ChromaDB 路径**：`build_kb_with_cloud_ocr.py` 的 `DB_PATH` 原使用 `./chroma_db`，写入位置与后端 `data/chroma_db` 不一致；现改为基于 `__file__` 动态计算，确保脚本产出与后端读取同一份数据库。
- **修复无 OCR 凭据时无法复用缓存的问题**：当 `ocr_pages.json` 已缓存全部页面时，脚本自动跳过 OCR 引擎初始化，直接进入目录解析与分块阶段。
- **全书重建结果**：
  - 目录条目：160 个；
  - 页码偏移：中位数 **10**；
  - 语义分块前（TOC 树切分）：约 120+ 个 chunk；
  - 语义分块后：**1144 个 chunk**；
  - Embedding 批次：36 batches，耗时约 **10 分 51 秒**；
  - ChromaDB `cs408_kb` 最终入库：**1144 条文档**。
- 状态更新：知识库 chunk 粒度从章节级细化到语义主题级，检索精度显著提升。

### 2026-04-15
- **新增知识库浏览页面（Knowledge Browser）**：
  1. 前端引入 `vue-router`，在 `ChatPage` 顶部增加"知识库"入口按钮，点击后跳转到 `/kb`；
  2. 新建 `KnowledgeBrowser.vue`：左侧为 `el-tree` 章节树（按科目→章节层级），右侧展示选中章节下的所有 chunk 卡片；
  3. 每张卡片显示章节名、页码范围（`pX-Y`）和 chunk 原文，并提供"查看PDF原文"按钮；
  4. 点击"查看PDF原文"通过 `window.open` 打开后端静态文件服务提供的 PDF 链接，并附加 `#page=页码` 锚点，浏览器会自动跳转到对应页面。
- **后端配套支持**：
  1. 新增 `/api/kb/chapters`：遍历 ChromaDB 全部元数据，按 `subject` 和 `chapter`（去除 part 后缀）构建树形返回；
  2. 新增 `/api/kb/chapter_docs`：按 `subject` + `chapter` 过滤并返回该章节下所有 chunk 的原文与元数据，按页码排序；
  3. 使用 `fastapi.staticfiles.StaticFiles` 将 `C:/Users/31314/Desktop/rag/408` 目录挂载到 `/static/408`，使浏览器可直接访问本地 PDF 文件。
- **验证结果**：
  - `/api/kb/chapters` 正确返回 160 个章节节点；
  - `/api/kb/chapter_docs?subject=数据结构&chapter=二叉树的定义` 成功召回对应 chunk；
  - 静态文件 `http://localhost:8001/static/408/...pdf#page=125` 可在浏览器新标签页直接打开并跳转页码；
  - 前端 `vite build` 编译通过，路由切换正常。
- 状态更新：系统已具备"按章节浏览教材原文 + 一键定位到 PDF"的能力，填补了前端知识库浏览器功能的空白。

<!-- 后续操作请在此追加 -->

### 2026-04-17
- **后端代码审查与优化**：
  1. `main.py` 中 `stream_chat()` 不再直接访问 `session_mgr._sessions`，改用 `session_mgr.ensure_session()` 封装方法；
  2. `kb_chapter_docs()` 从全量 `collection.get()` 改为使用 `where={"subject": subject}` 在数据库层面过滤，大幅降低内存占用；
  3. `kb_chapters()` 的 `collection.get()` 增加 `limit=20000`，防止未来数据膨胀导致一次性加载过多；
  4. 静态文件挂载路径从硬编码 `C:/Users/...` 改为基于 `__file__` 的相对路径（`parent.parent.parent / "408"`），提升可移植性；
  5. `update_llm_settings()` 将已弃用的 Pydantic v1 `config.dict()` 替换为 v2 的 `config.model_dump()`；
  6. `llm_client.py` 增加客户端缓存：配置变化时才重建 `AsyncOpenAI`/`AsyncAnthropic` 实例，避免重复连接；
  7. 删除 `models.py` 中未使用的 `LLMConfigOut` 模型。
- **前端代码审查与优化**：
  1. `ChatPage.vue` 移除未使用的 `originalRule`/`originalBlockRule` 变量；
  2. `sendMessage()` 将 `loading = false` 移入 `finally` 块，确保无论流结束、报错还是断网，发送按钮都会恢复；
  3. `KnowledgeBrowser.vue` 将全局硬编码 `pdfName` 改为基于 `doc.subject` 的 `PDF_MAP` 动态解析，消除单本 PDF 的硬编码依赖。
- **修复"查看PDF原文"功能失效**：
  1. **根因 1**：静态文件挂载路径 `Path(__file__).resolve().parent.parent.parent.parent / "408"` 多了一层 `parent`，指向 `Desktop` 而非项目根目录，导致 PDF 404。
  2. **修复 1**：修正为 `parent.parent.parent / "408"`，指向 `rag/408`。
  3. **根因 2**：`PDF_MAP` 的键为 `数据结构考研复习全书`，但实际 `doc.source` 为 `27版竟成数据结构-云OCR校准版`，`includes` 匹配失败返回空字符串。
  4. **修复 2**：将 `PDF_MAP` 的键改为标准化的 `数据结构`（与 `doc.subject` 一致），`resolvePdfName` 直接按 `subject` 查找。
- **修复设置 API 返回被掩码的 API Key**：
  - 根因：`GET /api/settings/llm` 调用 `get_llm_config(mask_api_key=True)` 默认掩码，导致前端设置弹窗显示 `****`。
  - 修复：改为 `mask_api_key=False`，让前端获得完整 Key；前端 `el-input type="password" show-password` 仍提供视觉保护，可点击眼睛图标查看明文。
- **验证结果**：
  - 后端 `/health` 返回 `{"status":"ok","kb_documents":1144}`；
  - 设置弹窗正确显示完整的 DeepSeek API Key；
  - 流式对话 SSE 逐字输出正常，知识来源引用和页码显示正确；
  - 知识库浏览器章节树加载正常，文档卡片正确显示；
  - "查看PDF原文"按钮成功在新标签页打开 PDF 并跳转到对应页码（如 `page=351`）。

