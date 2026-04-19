#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调用外部云 OCR（百度/阿里/腾讯）处理扫描/编码损坏的 408 PDF，
产出干净文本并按章节分块，最终写入 ChromaDB。

使用步骤：
1. 注册云 OCR 服务并获取密钥（推荐百度，免费额度最多）。
2. 配置环境变量（见下方说明）。
3. 运行脚本：python build_kb_with_cloud_ocr.py

环境变量配置（三选一即可）：
  • 百度智能云（推荐）
    BAIDU_OCR_API_KEY=你的ApiKey
    BAIDU_OCR_SECRET_KEY=你的SecretKey
    BAIDU_OCR_APP_ID=你的AppID（可选）
  • 阿里云
    ALIYUN_OCR_ACCESS_KEY_ID=你的AccessKeyId
    ALIYUN_OCR_ACCESS_KEY_SECRET=你的AccessKeySecret
  • 腾讯云
    TENCENT_OCR_SECRET_ID=你的SecretId
    TENCENT_OCR_SECRET_KEY=你的SecretKey
"""

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.ocr_engine import build_ocr_engine

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

# ------------------------------------------------------------------
# 用户配置区
# ------------------------------------------------------------------
# 自动发现 408 目录下的 PDF（避免中文编码问题）
_PDF_DIR = Path("C:/Users/31314/Desktop/rag/408")
_PDF_FILES = sorted([p for p in _PDF_DIR.glob("*.pdf") if "竟成" in p.name])
if not _PDF_FILES:
    raise FileNotFoundError("未在 408 目录下找到竟成版 PDF")
INPUT_PDF = str(_PDF_FILES[0])

SUBJECT_NAME = "数据结构"
SOURCE_NAME = "27版竟成数据结构-云OCR校准版"
OUTPUT_DIR = "C:/Users/31314/Desktop/rag/408/ocr_output"
DPI = 200
DB_PATH = str(Path(__file__).resolve().parent / "chroma_db")

COLLECTION_NAME = "cs408_kb"
MODEL_NAME = "BAAI/bge-m3"
BATCH_SIZE = 32

# OCR 并发控制（注意各家云服务商都有 QPS 限制，百度高精度版默认 QPS≈2）
OCR_CONCURRENCY = 2

# 调试开关：设为 20 表示只处理前 20 页测试；0 表示处理全部
TEST_MAX_PAGES = 0


# ------------------------------------------------------------------
# 数据结构
# ------------------------------------------------------------------
@dataclass
class TextChunk:
    title: str
    level: int
    page_start: int
    page_end: int
    content: str
    subject: str = ""
    source_file: str = ""


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------
def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def pdf_to_images(pdf_path: str, out_dir: str, dpi: int = DPI, max_pages: int = 0):
    """将 PDF 转为 PNG，返回 (页码, 图片路径) 列表。"""
    doc = fitz.open(pdf_path)
    total = doc.page_count if max_pages == 0 else min(max_pages, doc.page_count)
    results = []
    print(f"[渲染] 共 {total} 页，DPI={dpi}")
    for i in range(total):
        page = doc[i]
        pix = page.get_pixmap(dpi=dpi)
        img_path = os.path.join(out_dir, f"page_{i+1:04d}.png")
        pix.save(img_path)
        results.append((i + 1, img_path))
        if (i + 1) % 20 == 0 or (i + 1) == total:
            print(f"       已渲染 {i+1}/{total}")
    doc.close()
    return results


async def run_ocr(image_list: List[tuple], ocr_engine, progress_path: str):
    """并发 OCR，支持断点续传。"""
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            results = json.load(f)
        print(f"[续传] 已处理 {len(results)}/{len(image_list)} 页")
    else:
        results = {}

    semaphore = asyncio.Semaphore(OCR_CONCURRENCY)

    async def _task(page_num: int, img_path: str):
        if str(page_num) in results:
            return
        async with semaphore:
            try:
                text = ocr_engine.recognize_image(img_path)
                results[str(page_num)] = text
                with open(progress_path, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
                print(f"  -> 完成 page {page_num}")
            except Exception as e:
                print(f"  -> 失败 page {page_num}: {e}")

    tasks = [asyncio.create_task(_task(pnum, path)) for pnum, path in image_list]
    await asyncio.gather(*tasks)
    return results


# ------------------------------------------------------------------
# 文本清洗
# ------------------------------------------------------------------
JC_HEADER_PATTERNS = [
    re.compile(r"^①.*408.*辅导书.*"),
    re.compile(r"^②.*电子版供参考.*"),
    re.compile(r"^③.*27考研推出.*"),
    re.compile(r"^④.*报辅导班.*书籍勘误.*"),
    re.compile(r"^[③④]$"),  # 过滤单独一行的 ③/④ 符号
    re.compile(r"^[竞竟]成·目录$"),
    re.compile(r"^[竞竟]成\s*[·•].*$"),  # 过滤 "竞成·第1章编程基础" / "竞成·1.2变量与数据类型"
]

# 额外过滤：OCR 中 ③/④ 符号和广告文案被拆成两行的场景
JC_AD_PATTERNS = [
    re.compile(r"^[竞竟]成针对27考研推出.*"),
    re.compile(r"^报辅导班.*竟成书籍勘误.*"),
]

JC_FOOTER_PATTERNS = [
    re.compile(r".*官方淘宝店.*"),
    re.compile(r".*官方公众.*"),
    re.compile(r".*B站.*账号.*"),
    re.compile(r".*公众号.*账号.*"),
    re.compile(r".*竟成针对27考研推出.*"),  # 底部广告文案
    re.compile(r"·[ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹivx]+·"),  # 罗马数字页码装饰
]


def clean_page_text(text: str) -> str:
    """去除竞成教材的页眉页脚、水印、广告。"""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        # 过滤头部/页眉广告
        if any(p.match(line_stripped) for p in JC_HEADER_PATTERNS):
            continue
        # 过滤拆行广告
        if any(p.match(line_stripped) for p in JC_AD_PATTERNS):
            continue
        # 过滤尾部/页脚广告
        if any(p.search(line_stripped) for p in JC_FOOTER_PATTERNS):
            continue
        # 过滤纯数字页码
        if re.match(r"^\d+$", line_stripped):
            continue
        cleaned.append(line_stripped)
    return "\n".join(cleaned)


# ------------------------------------------------------------------
# 目录重建（从 OCR 结果里解析目录）
# ------------------------------------------------------------------
def parse_toc_from_ocr(results: dict) -> List[Tuple[int, str, int]]:
    """
    从 OCR 结果的前几页（目录页）解析出 TOC 结构。
    返回 [(level, title, page), ...]。
    针对竟成教材目录格式优化：编号和标题之间可能没有空格，
    页码可能在下一行单独出现。
    """
    toc_pages = []
    for pnum in sorted(results.keys(), key=int):
        if int(pnum) <= 10:
            toc_pages.append(results[pnum])

    toc_lines = "\n".join(toc_pages).splitlines()

    # 正则模式（标题和编号之间空格可选）
    chapter_pat = re.compile(r"^第\s*\d+\s*章\s*(.+)$")
    section_pat = re.compile(r"^(\d+\.\d+)\s*(.+)$")
    subsec_pat = re.compile(r"^(\d+\.\d+\.\d+)\s*(.+)$")
    pure_num_pat = re.compile(r"^\d+$")

    entries = []
    last_entry = None

    for raw_line in toc_lines:
        line = raw_line.strip()
        if not line:
            continue

        # 跳过目录页里的广告和水印
        if line.startswith("①") or line.startswith("②") or line.startswith("③") or line.startswith("④"):
            continue
        if "淘宝店" in line or "B站" in line or "公众号" in line:
            continue
        if line in {"目录", "竟成·目录"}:
            continue
        if re.match(r"^·[ⅰⅱⅲⅳⅴⅵⅶⅷⅸⅹivx]+·$", line):
            continue

        # 如果当前行是纯数字，可能是上一行的页码
        if pure_num_pat.match(line) and last_entry is not None:
            last_entry = (last_entry[0], last_entry[1], int(line))
            entries[-1] = last_entry
            continue

        # 尝试从行尾提取页码（如 "1.1前言...... 1"）
        page = 0
        pm = re.search(r"([\.·\s]+)(\d+)\s*$", line)
        if pm:
            line = line[: pm.start()].strip(".· ")
            page = int(pm.group(2))

        # 子章节 1.2.1
        m = subsec_pat.match(line)
        if m:
            title = m.group(2).strip(".· ")
            last_entry = (3, title, page)
            entries.append(last_entry)
            continue

        # 章节 1.1
        m = section_pat.match(line)
        if m:
            title = m.group(2).strip(".· ")
            last_entry = (2, title, page)
            entries.append(last_entry)
            continue

        # 大章 第1章
        m = chapter_pat.match(line)
        if m:
            title = m.group(1).strip(".· ")
            last_entry = (1, title, page)
            entries.append(last_entry)
            continue

    # 页码为 0 时做简单后向插值
    for i in range(len(entries) - 1, -1, -1):
        if entries[i][2] == 0 and i + 1 < len(entries):
            entries[i] = (entries[i][0], entries[i][1], max(0, entries[i + 1][2] - 1))

    # 过滤掉纯导航性条目（保留大章，过滤小节里的导航项）
    skip_words = {"章末总结", "习题", "答案与解析", "真题演练", "习题精编", "本章总结"}
    filtered = []
    for level, title, page in entries:
        if any(sw in title for sw in skip_words) and level >= 2:
            continue
        filtered.append((level, title, page))

    return filtered


def detect_page_offset(results: dict, toc: List[Tuple[int, str, int]]) -> int:
    """
    自动检测目录页码与实际 PDF 页码的偏移量。
    方法：取多个页码 > 0 的目录条目，在内容页中搜索首次出现位置，
    统计偏移量分布并取中位数，从而得到稳定的偏移估计。
    """
    if not toc:
        return 0

    max_page = max(int(k) for k in results.keys())
    offsets = []

    # 候选条目：前 30 个页码 > 0 且标题不太泛化的条目
    candidates = [
        (level, title, page)
        for level, title, page in toc
        if page > 0 and len(title.strip()) >= 2
    ][:30]

    skip_keywords = {"前言", "目录", "绪论", "章末总结", "本章总结", "习题", "答案", "解析", "真题"}

    for level, title, toc_page in candidates:
        keyword = title[:10].strip()
        if not keyword or any(sk in keyword for sk in skip_keywords):
            continue

        # 从第 11 页开始搜索，跳过 front matter / 目录页
        search_start = 11
        for p in range(search_start, min(max_page + 1, 100)):
            txt = clean_page_text(results.get(str(p), ""))
            if keyword in txt:
                offset = p - toc_page
                offsets.append(offset)
                break

    if not offsets:
        # 降级：尝试 level 1 中 page == 0 的条目（如“编程基础”）
        for level, title, page in toc:
            if level == 1:
                keyword = title[:10].strip()
                if not keyword:
                    continue
                for p in range(search_start, min(max_page + 1, 100)):
                    txt = clean_page_text(results.get(str(p), ""))
                    if keyword in txt:
                        offset = p - page
                        print(f"[偏移检测] level 1 标题 '{keyword}' 出现在 PDF 第 {p} 页，目录页码 {page}，偏移量 = {offset}")
                        return offset
                break
        print("[偏移检测] 未找到有效偏移，默认偏移量 = 0")
        return 0

    offsets.sort()
    offset = offsets[len(offsets) // 2]
    print(f"[偏移检测] 样本偏移量: {offsets}，取中位数 = {offset}")
    return offset


def chunk_by_toc(results: dict, toc: List[Tuple[int, str, int]], page_offset: int = 0) -> List[TextChunk]:
    """按重建的目录切分文本，支持页码偏移校正，并避免父子条目内容重叠。"""
    if not toc:
        # 无目录时退化为全书一个 chunk
        all_text = "\n\n".join(
            clean_page_text(results[p]) for p in sorted(results.keys(), key=int)
        )
        return [
            TextChunk(
                title="全文",
                level=1,
                page_start=1,
                page_end=max(int(k) for k in results.keys()),
                content=all_text,
                subject=SUBJECT_NAME,
                source_file=SOURCE_NAME,
            )
        ]

    # 过滤掉页码为 0 或超出范围的条目，并应用偏移
    max_page = max(int(k) for k in results.keys())
    valid_toc = []
    for level, title, page in toc:
        actual_page = page + page_offset
        if actual_page <= 0 or actual_page > max_page:
            continue
        valid_toc.append((level, title, actual_page))

    # 预计算每个条目的结束页码
    entries_with_end = []
    for idx, (level, title, start_page) in enumerate(valid_toc):
        end_page = max_page
        for next_level, _, next_page in valid_toc[idx + 1 :]:
            if next_level <= level:
                end_page = next_page - 1
                break
        end_page = max(start_page, end_page)
        entries_with_end.append((level, title, start_page, end_page))

    # 利用栈构建目录树：找出每个条目的直接子条目
    children_indices = [[] for _ in entries_with_end]
    stack = []  # (level, index)
    for idx, (level, title, start, end) in enumerate(entries_with_end):
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            parent_idx = stack[-1][1]
            parent_level = stack[-1][0]
            if level == parent_level + 1:
                children_indices[parent_idx].append(idx)
        stack.append((level, idx))

    chunks = []
    for i, (level, title, start_page, end_page) in enumerate(entries_with_end):
        children = children_indices[i]
        if children:
            # 非叶子节点：只保留第一个子节点之前的页面作为引言/概览
            first_child_start = entries_with_end[children[0]][2]
            actual_end = min(end_page, first_child_start - 1)
        else:
            # 叶子节点：保留完整范围
            actual_end = end_page

        if actual_end < start_page:
            continue

        parts = []
        for p in range(start_page, actual_end + 1):
            if str(p) in results:
                txt = clean_page_text(results[str(p)])
                if txt.strip():
                    parts.append(txt)
        content = "\n\n".join(parts)
        if len(content) < 30:
            continue

        chunks.append(
            TextChunk(
                title=title,
                level=level,
                page_start=start_page,
                page_end=actual_end,
                content=content,
                subject=SUBJECT_NAME,
                source_file=SOURCE_NAME,
            )
        )

    return chunks


def split_large_chunks(chunks: List[TextChunk], max_chars: int = 3000, overlap: int = 200) -> List[TextChunk]:
    """对超长 chunk 做滑动窗口切分（保留作为降级方案）。"""
    result = []
    for ck in chunks:
        if len(ck.content) <= max_chars:
            result.append(ck)
            continue
        paras = ck.content.split("\n\n")
        buf = ""
        part_idx = 1
        for para in paras:
            if not para.strip():
                continue
            if len(buf) + len(para) + 2 > max_chars and buf:
                result.append(
                    TextChunk(
                        title=f"{ck.title} (part{part_idx})",
                        level=ck.level,
                        page_start=ck.page_start,
                        page_end=ck.page_end,
                        content=buf.strip(),
                        subject=ck.subject,
                        source_file=ck.source_file,
                    )
                )
                buf = (buf[-overlap:] + "\n\n" + para).strip() if overlap > 0 else para
                part_idx += 1
            else:
                buf = (buf + "\n\n" + para).strip() if buf else para
        if buf.strip():
            result.append(
                TextChunk(
                    title=f"{ck.title} (part{part_idx})",
                    level=ck.level,
                    page_start=ck.page_start,
                    page_end=ck.page_end,
                    content=buf.strip(),
                    subject=ck.subject,
                    source_file=ck.source_file,
                )
            )
    return result


_SENTENCE_SPLIT_RE = re.compile(r"([。！？.?!])")


def split_sentences(text: str) -> List[str]:
    """按中文/英文句子结束标点拆分，保留标点。"""
    parts = _SENTENCE_SPLIT_RE.split(text)
    sentences = []
    for i in range(0, len(parts), 2):
        s = parts[i]
        if i + 1 < len(parts):
            s += parts[i + 1]
        s = s.strip()
        if s:
            sentences.append(s)
    return sentences


def split_to_semantic_units(text: str, max_unit_len: int = 800) -> List[str]:
    """
    将文本拆分为语义单元。优先按段落边界（双换行或空行），
    若段落过长则按句子边界进一步拆分，并合并过短碎片。
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    units = []
    for block in blocks:
        if len(block) <= max_unit_len:
            units.append(block)
            continue
        # 段落过长：按句子拆分并合并极短句
        sentences = split_sentences(block)
        merged = []
        buf = ""
        for s in sentences:
            if len(buf) + len(s) < 50:
                buf += s
            else:
                if buf:
                    merged.append(buf.strip())
                buf = s
        if buf:
            merged.append(buf.strip())
        units.extend([m for m in merged if len(m) >= 10])
    return units


def semantic_split_chunks(
    chunks: List[TextChunk],
    model: SentenceTransformer,
    max_chars: int = 3000,
    min_chars: int = 300,
    similarity_threshold: float = 0.72,
) -> List[TextChunk]:
    """
    对超长 chunk 按段落边界 + 语义相似度动态切分。
    短 chunk（<= max_chars）直接保留；长 chunk 拆分为语义单元后，
    计算相邻单元 embedding 的余弦相似度，在相似度低于阈值或达到上限处分割。
    """
    result = []
    for ck in chunks:
        if len(ck.content) <= max_chars:
            result.append(ck)
            continue

        units = split_to_semantic_units(ck.content)
        if len(units) <= 1:
            result.append(ck)
            continue

        embeddings = model.encode(units, normalize_embeddings=True, batch_size=64)

        groups = []
        current_group = [units[0]]
        current_len = len(units[0])

        for i in range(1, len(units)):
            unit = units[i]
            sim = float(np.dot(embeddings[i - 1], embeddings[i]))
            new_len = current_len + len(unit) + 1  # +1 for newline separator

            must_split = new_len > max_chars
            should_split = sim < similarity_threshold and current_len >= min_chars

            if must_split or should_split:
                groups.append(current_group)
                current_group = [unit]
                current_len = len(unit)
            else:
                current_group.append(unit)
                current_len = new_len

        if current_group:
            groups.append(current_group)

        # 后处理：若最后一组过短，尝试与前一个组合并
        if len(groups) >= 2:
            last_len = sum(len(u) for u in groups[-1])
            if last_len < min_chars:
                groups[-2].extend(groups[-1])
                groups.pop()

        for part_idx, group in enumerate(groups, 1):
            content = "\n".join(group)
            result.append(
                TextChunk(
                    title=f"{ck.title} (part{part_idx})",
                    level=ck.level,
                    page_start=ck.page_start,
                    page_end=ck.page_end,
                    content=content,
                    subject=ck.subject,
                    source_file=ck.source_file,
                )
            )

    return result


# ------------------------------------------------------------------
# 知识库写入
# ------------------------------------------------------------------
def build_kb(documents: List[str], metadatas: List[dict], ids: List[str], model=None):
    """写入 ChromaDB。"""
    if model is None:
        print(f"\n[加载模型] {MODEL_NAME}")
        model = SentenceTransformer(MODEL_NAME)

    print(f"\n[生成 embeddings] 共 {len(documents)} 条")
    embeddings = model.encode(documents, normalize_embeddings=True, show_progress_bar=True)

    print(f"[写入 ChromaDB] {DB_PATH}")
    client = chromadb.PersistentClient(path=DB_PATH)
    collection = client.get_or_create_collection(name=COLLECTION_NAME)

    # 清理旧的同来源数据
    try:
        existing = collection.get()
        old_ids = [i for i in existing["ids"] if i.startswith("ocr_")]
        if old_ids:
            collection.delete(ids=old_ids)
            print(f"       已清除旧 OCR 数据 {len(old_ids)} 条")
    except Exception as e:
        print(f"       清理旧数据失败（可忽略）: {e}")

    for i in range(0, len(documents), BATCH_SIZE):
        end = i + BATCH_SIZE
        collection.add(
            ids=ids[i:end],
            documents=documents[i:end],
            metadatas=metadatas[i:end],
            embeddings=embeddings[i:end].tolist(),
        )
    print(f"[完成] 知识库当前共 {collection.count()} 条文档")


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------
async def main():
    ensure_dir(OUTPUT_DIR)
    img_dir = os.path.join(OUTPUT_DIR, "pages")
    ensure_dir(img_dir)

    progress_path = os.path.join(OUTPUT_DIR, "ocr_pages.json")
    json_path = os.path.join(OUTPUT_DIR, "chunks.json")

    print("=" * 60)
    print("408 知识库构建 — 外部云 OCR 方案")
    print("=" * 60)

    # 2) 检查是否已有完整缓存，避免重复初始化 OCR 引擎
    cached_results = {}
    if os.path.exists(progress_path):
        with open(progress_path, "r", encoding="utf-8") as f:
            cached_results = json.load(f)
        print(f"[缓存检测] 已发现 OCR 缓存 {len(cached_results)} 页")

    # 计算目标页数
    doc = fitz.open(INPUT_PDF)
    target_pages = doc.page_count if TEST_MAX_PAGES == 0 else min(TEST_MAX_PAGES, doc.page_count)
    doc.close()

    if len(cached_results) >= target_pages:
        print("[跳过 OCR] 缓存已完整，直接进入目录解析与分块阶段")
        results = cached_results
    else:
        # 1) 初始化 OCR 引擎
        ocr_engine = build_ocr_engine()
        print(f"[OCR 引擎] {ocr_engine.name}")

        # PDF -> 图片
        image_list = pdf_to_images(INPUT_PDF, img_dir, DPI, TEST_MAX_PAGES)
        if not image_list:
            print("错误：没有生成任何图片")
            sys.exit(1)

        print(f"\n[开始 OCR] 并发数={OCR_CONCURRENCY}，请留意云服务商 QPS 限制...")
        results = await run_ocr(image_list, ocr_engine, progress_path)
        print(f"[OCR 完成] 成功/累计 {len(results)} 页")

        if len(results) == 0:
            print("错误：没有任何 OCR 结果")
            sys.exit(1)

    # 4) 从 OCR 结果重建目录并切分
    print("\n[重建目录] 从 OCR 结果解析 TOC...")
    toc = parse_toc_from_ocr(results)
    print(f"       解析到 {len(toc)} 个目录条目")
    for level, title, page in toc[:8]:
        print(f"       {'  ' * (level - 1)}{title}  (p{page})")

    page_offset = detect_page_offset(results, toc)
    chunks = chunk_by_toc(results, toc, page_offset=page_offset)

    # 提前加载 BGE-m3，用于语义分块和后续 Embedding（避免重复加载）
    print(f"\n[加载模型] {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME)

    chunks = semantic_split_chunks(
        chunks, model, max_chars=3000, min_chars=300, similarity_threshold=0.72
    )
    print(f"[语义分块完成] 共生成 {len(chunks)} 个文本块")
    for c in chunks[:5]:
        print(f"       [{c.level}] {c.title} | p{c.page_start}-{c.page_end} | {len(c.content)} 字符")

    # 保存 chunk 元信息
    chunk_data = [
        {
            "title": c.title,
            "level": c.level,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "subject": c.subject,
            "source_file": c.source_file,
            "content": c.content,
        }
        for c in chunks
    ]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(chunk_data, f, ensure_ascii=False, indent=2)
    print(f"[JSON 已保存] {json_path}")

    # 5) 写入 ChromaDB
    documents = [f"{c.title}\n{c.content}" for c in chunks]
    ids = [f"ocr_{i:05d}" for i in range(len(chunks))]
    metadatas = [
        {
            "subject": c.subject,
            "chapter": c.title,
            "source": c.source_file,
            "page_start": str(c.page_start),
            "page_end": str(c.page_end),
        }
        for c in chunks
    ]
    build_kb(documents, metadatas, ids, model=model)
    print("\n全部完成！")


if __name__ == "__main__":
    asyncio.run(main())
