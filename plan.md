# 面向研究生入学考试计算机专业课的智能学习系统

## 一、项目背景与目标
### 1.1 选题背景
- 408 计算机专业基础综合：数据结构、操作系统、计算机网络、计算机组成原理
- 知识点密集、逻辑性强、底层概念复杂
- 传统学习方式：纸质教材 + 网课，缺乏及时精准答疑
- 通用大模型存在"幻觉"问题，在专业知识上不够可靠
### 1.2 核心思路
- 引入 RAG（Retrieval-Augmented Generation，检索增强生成）
- 构建 408 垂直领域知识库
- 用大模型 + 精准检索实现"有源可溯"的智能答疑
### 1.3 性能指标
- 知识检索召回率 ≥ 85%
- 回答准确率 ≥ 80%
- 单轮响应延迟 ≤ 3 秒

## 二、技术架构
### 2.1 后端技术栈
- FastAPI：高性能异步 Web 框架
- LangChain：RAG 流程编排与大模型交互
- ChromaDB：开源向量数据库，存储 Embedding
- Python 自动化脚本：数据清洗与知识库构建流水线
### 2.2 前端技术栈
- Vue.js 3：渐进式前端框架
- 现代 UI 组件库（如 Element Plus / Ant Design Vue）
- SSE（Server-Sent Events）：流式接收大模型输出
### 2.3 AI 模型与算法
- Embedding 模型：BGE-m3（中文语义理解强）
- 重排序模型：BGE-Reranker（Cross-Encoder）
- 大语言模型：GLM-4 / 通义千问 / DeepSeek（商业 API 或本地部署）
- 检索策略：Dense Retrieval + Sparse Retrieval（BM25）混合检索

## 三、核心模块实现
### 3.1 知识库构建（Knowledge Base Construction）
#### 3.1.1 数据源采集
- 官方指定教材（PDF）
- 历年真题与权威解析（Markdown / PDF）
- 优质笔记与思维导图
#### 3.1.2 文档解析（Document Parsing）
- 文本类：PDF 转文本、Markdown 直接读取
- 复杂格式：Nougat / MinerU（处理 LaTeX 数学公式、代码块、图表）
- 手写/扫描内容：OCR 补充（如需要）
#### 3.1.3 文本分片（Chunking）
- 基础策略：固定长度分块（Fixed-size Chunking）+ 重叠
- 进阶策略：语义分块（Semantic Chunking）
  - 基于 Markdown 标题层级、段落边界智能分割
  - 代码块、公式尽量保持完整
#### 3.1.4 向量存储
- 使用 BGE-m3 生成文本 Embedding
- 存入 ChromaDB，附带元数据（来源、章节、页码、题型标签）
- 构建 408 四门科目的分集合（Collection）或统一索引

### 3.2 RAG 检索算法（Retrieval & Generation）
#### 3.2.1 查询预处理
- Query Rewriting：扩展同义词、补全专业术语
- Query Decomposition：复杂问题拆分为子问题
#### 3.2.2 混合检索（Hybrid Retrieval）
- Dense Retrieval：向量相似度搜索（ChromaDB）
- Sparse Retrieval：BM25 关键词检索（如 whoosh / rank_bm25）
- 结果融合：加权合并两种检索的 Top-K 结果
#### 3.2.3 重排序（Reranking）
- 使用 BGE-Reranker（Cross-Encoder）对初筛结果精排
- 动态筛选最相关的 Top-K 文本片段
#### 3.2.4 生成增强
- Prompt Engineering 设计系统指令：
  - "你是 408 考研辅导专家，基于以下参考资料回答问题"
  - "如果资料不足以回答，请明确说明"
- 上下文拼接：检索结果 + 用户问题 → LLM
- 引用标注：在答案中标注知识来源

### 3.3 对话系统（Conversational System）
#### 3.3.1 流式响应
- FastAPI SSE（Server-Sent Events）输出大模型生成内容
- 前端实时渲染，降低"等待焦虑"
- 支持自定义 event 类型：message / source / end
#### 3.3.2 对话历史管理
- Conversational Buffer Memory 存储多轮上下文
- 支持会话列表、历史记录回溯、清空对话
#### 3.3.3 知识溯源
- 返回答案的同时，附带引用的原始文本片段
- 前端展示"来源卡片"，支持一键定位到教材原文

### 3.4 Web 前端（Frontend UI）
#### 3.4.1 页面设计
- 整体风格：简洁、学术、专注
- 核心页面：
  - 对话页面（类 ChatGPT 交互）
  - 知识库浏览页面（按科目/章节查看）
  - 历史会话页面
#### 3.4.2 交互细节
- 用户输入框支持 Markdown 快速编辑
- AI 答案支持代码高亮、公式渲染（MathJax / KaTeX）
- 侧边栏展示知识来源引用
#### 3.4.3 性能优化
- 全栈异步 I/O，避免阻塞
- 前端骨架屏/打字机效果提升感知性能

## 四、开发计划（16周）
### 第 1-4 周：文献调研与需求分析
- 阅读 LLM、RAG、LangChain 相关文献
- 调研 408 考试大纲与教材结构
- 完成开题报告与技术选型
### 第 5-7 周：数据预处理与知识库构建
- 收集并清洗教材、真题、笔记数据
- 实现文档解析与分块流水线
- 生成 Embedding 并导入 ChromaDB
- 构建 408 垂直知识库
### 第 8-10 周：系统核心开发
- 后端：实现 RAG 检索链路（检索 → 重排 → 生成）
- 后端：搭建 FastAPI 接口（对话、历史、知识溯源）
- 前端：Vue.js 项目搭建与核心页面开发
- 前后端联调：SSE 流式对话打通
### 第 11-14 周：系统测试与论文撰写
- 功能测试：单元测试、接口测试
- 性能测试：JMeter 压测、延迟监控（TTFT）
- 效果评估：构建测试集，验证召回率与准确率
- 论文撰写：按学校规范完成毕业论文
### 第 15 周：答辩准备
- PPT 制作与演练
- 系统演示视频录制
- 最终修改与定稿

## 五、关键技术难点与解决方案
### 5.1 复杂内容的解析与分块
- 难点：教材中包含大量数学公式、代码、图表
- 方案：采用 Nougat / MinerU 进行学术 PDF 解析，结合语义分块策略
### 5.2 检索召回率的提升
- 难点：单一向量检索在特定专业术语上可能漏召
- 方案：Dense + Sparse 混合检索 + Cross-Encoder 重排序
### 5.3 响应延迟控制
- 难点：大模型 API 调用和网络传输耗时
- 方案：
  - 全链路异步 I/O（FastAPI + aiohttp）
  - SSE 流式输出，降低首字延迟
  - 合理控制检索 Top-K 数量与 Prompt 长度
### 5.4 大模型幻觉抑制
- 难点：模型可能编造不存在的概念或公式
- 方案：
  - RAG 强制基于检索上下文回答
  - Prompt 中明确约束："只根据提供的资料回答，不确定时说明"

## 六、评估与测试方案
### 6.1 数据集构建
- 收集 408 统考历年真题及标准答案
- 按科目（数据结构、操作系统、计网、计组）分类标注
- 涵盖概念解释、计算题、综合分析题
### 6.2 效果评估
- 自动评估：LLM-as-a-Judge（用 GPT-4/GLM-4 评判答案质量）
- 人工评估：邀请考研辅导老师或高年级学生核对答案准确性
- 指标监控：召回率、准确率、延迟（TTFT）
### 6.3 压力测试
- 使用 JMeter 模拟并发用户请求
- 监控接口响应时间与系统资源占用

## 七、参考资料（Context7 查询）
### LangChain RAG
- RAG Agent vs 2-step RAG vs Hybrid RAG 三种模式
- 使用 `RecursiveCharacterTextSplitter` 进行文档分块
- 使用 `create_agent` 构建带检索工具的 Agent
### ChromaDB
- `chromadb.Client()` 本地/内存模式快速原型
- `collection.add()` 添加文档与元数据
- `collection.query()` 支持文本查询、批量查询、元数据过滤
- 可配置自定义 Embedding Function（如 BGE-m3）
### FastAPI SSE
- `EventSourceResponse` 实现 Server-Sent Events
- 支持 `AsyncIterable` 流式输出
- 支持自定义 `ServerSentEvent`（event / id / retry 等字段）
- 自动处理 `Cache-Control: no-cache` 与 keep-alive
### Vue.js
- 推荐使用 `<script setup>` 语法提升开发体验
- 响应式数据绑定与组件化架构
- 可渐进式扩展为复杂单页应用（SPA）
