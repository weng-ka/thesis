#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ENV: Thesis
"""
單篇勞工新聞摘要生成腳本。

流程：讀取 raw 原文 + structured JSON →（可選）RAG 即時檢索相關法條 → LLM 生成摘要。
使用 --no-rag 時僅使用原文與結構化資料，不檢索法條。

Usage:
    # 只給新聞編號 + 指定要生成哪些版本（未指定會報錯）
    python3 src/scripts/summarize_news.py 0099 --rag
    python3 src/scripts/summarize_news.py 0099 --structured-only
    python3 src/scripts/summarize_news.py 0099 --rag --structured-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

import os

API_KEY = os.environ["LLM_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "deepseek-v3")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")

SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from openai import OpenAI

from prompts.summary_prompt import SYSTEM_PROMPT, build_user_prompt
from prompts.summary_prompt_structured_only import (
    SYSTEM_PROMPT_STRUCTURED_ONLY,
    build_user_prompt_structured_only,
)
from prompts.summary_prompt_raw_only import (
    SYSTEM_PROMPT_RAW_ONLY,
    build_user_prompt_raw_only,
)
from retrieval.retrieve import retrieve_laws_for_article
from scripts.extract_schema import extract_structured_from_raw

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """取得共用的 OpenAI client。"""
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


def _read_raw(raw_path: Path) -> str:
    """
    讀取 raw txt 並返回完整文本（標題 + 內文）。

    Args:
        raw_path: raw 檔案路徑。

    Returns:
        原始新聞全文。
    """
    content = raw_path.read_text(encoding="utf-8")

    title_m = re.search(r"【標題】\s*\n(.+?)(?=\n\s*【)", content, re.DOTALL)
    body_m = re.search(r"【內文】\s*\n(.+)", content, re.DOTALL)

    title = title_m.group(1).strip() if title_m else ""
    body = body_m.group(1).strip() if body_m else content.strip()

    if title:
        return f"{title}\n\n{body}"
    return body


def call_llm_for_summary(
    system_prompt: str,
    user_prompt: str,
    max_retries: int = 3,
) -> str:
    """
    呼叫 LLM 生成摘要，含 exponential backoff 重試。

    Args:
        system_prompt: system 指令。
        user_prompt: 包含原文 / 結構化資訊 / 法條的 user prompt。
        max_retries: 最大重試次數。

    Returns:
        LLM 輸出的純文字摘要。

    Raises:
        RuntimeError: 超過重試次數仍失敗。
    """
    client = _get_client()
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
            )
            text = response.choices[0].message.content or ""
            text = re.sub(r"^```(?:markdown)?\s*\n?", "", text.strip())
            text = re.sub(r"\n?```\s*$", "", text).strip()
            return text

        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)
                print(
                    f"[WARN] LLM 呼叫失敗（第 {attempt + 1} 次），"
                    f"{wait}s 後重試：{e}",
                    file=sys.stderr,
                )
                time.sleep(wait)

    raise RuntimeError(f"LLM 呼叫失敗（已重試 {max_retries} 次）：{last_error}")


def summarize_single(
    raw_path: Path,
    structured: dict,
    *,
    use_rag: bool = True,
    top_k: int = 10,
    max_retries: int = 3,
) -> str:
    """
    對單篇新聞執行摘要流程：讀取 →（可選）RAG 檢索 → LLM 生成。

    Args:
        raw_path: raw txt 路徑。
        structured: 即時抽取或預先生成的 structured dict。
        use_rag: 若 True 則檢索法條並使用含 RAG 的 prompt；若 False 則僅用原文與結構化資料。
        top_k: RAG 檢索的 Top-k 法條數量（use_rag 時有效）。
        max_retries: LLM 呼叫重試次數。

    Returns:
        生成的摘要文字。
    """
    raw_text = _read_raw(raw_path)

    if use_rag:
        print("正在檢索相關法條…", file=sys.stderr, flush=True)
        laws_text = retrieve_laws_for_article(structured, top_k=top_k)
        if not laws_text:
            print("[WARN] RAG 未檢索到任何法條。", file=sys.stderr)
        user_prompt = build_user_prompt(raw_text, structured, laws_text)
        system_prompt = SYSTEM_PROMPT
    else:
        user_prompt = build_user_prompt_structured_only(raw_text, structured)
        system_prompt = SYSTEM_PROMPT_STRUCTURED_ONLY

    print("正在调用 LLM 生成摘要…", file=sys.stderr, flush=True)
    summary = call_llm_for_summary(system_prompt, user_prompt, max_retries=max_retries)

    return summary


def summarize_single_raw_only(
    raw_path: Path,
    *,
    max_retries: int = 3,
) -> str:
    """
    僅使用 raw 原文執行摘要流程，不讀取結構化資料，也不使用 RAG。

    Args:
        raw_path: raw txt 路徑。
        max_retries: LLM 呼叫重試次數。

    Returns:
        生成的摘要文字。
    """
    raw_text = _read_raw(raw_path)
    user_prompt = build_user_prompt_raw_only(raw_text)
    system_prompt = SYSTEM_PROMPT_RAW_ONLY

    print("正在调用 LLM 生成（raw-only）摘要…", file=sys.stderr, flush=True)
    summary = call_llm_for_summary(system_prompt, user_prompt, max_retries=max_retries)

    return summary


def _normalize_news_id(news_id: str) -> str:
    """
    將使用者輸入的新聞編號正規化成 4 位數字字串（例如：'99' → '0099'）。

    Args:
        news_id: 使用者輸入（允許 1~4 位數字，或已帶前導 0 的 4 位數字）。

    Returns:
        4 位數字字串。

    Raises:
        ValueError: 輸入不是純數字或長度不在 1~4。
    """
    s = (news_id or "").strip()
    if not s.isdigit():
        raise ValueError(f"news_id 必須是純數字：{news_id!r}")
    if not (1 <= len(s) <= 4):
        raise ValueError(f"news_id 長度需為 1~4 位：{news_id!r}")
    return s.zfill(4)


def _pick_single_match(paths: Iterable[Path], *, label: str) -> Path:
    """
    從 glob 結果中挑出唯一檔案；若 0 或多個則直接報錯（避免用錯檔）。

    Args:
        paths: 候選路徑。
        label: 用於錯誤訊息（例如 'raw' / 'structured'）。

    Returns:
        唯一匹配的路徑。

    Raises:
        FileNotFoundError: 找不到任何匹配。
        RuntimeError: 匹配到多個檔案（需要使用者修正檔名或改用舊入口）。
    """
    items = sorted(paths)
    if not items:
        raise FileNotFoundError(f"找不到 {label} 檔案（glob 無匹配）")
    if len(items) > 1:
        shown = "\n".join(f"- {p}" for p in items[:20])
        more = "" if len(items) <= 20 else f"\n...（另有 {len(items) - 20} 個省略）"
        raise RuntimeError(
            f"{label} 檔案匹配到多個，無法自動選擇：\n{shown}{more}\n"
            f"請調整檔名讓 {label} 只匹配一個檔，或改用舊入口手動指定 --{label}。"
        )
    return items[0]


def _resolve_paths_by_id(news_id_4: str) -> tuple[Path, Path]:
    """
    依 4 位數字新聞編號自動解析 raw/structured 檔案路徑。

    Args:
        news_id_4: 4 位數字字串（例如 '0099'）。

    Returns:
        (raw_path, structured_path)
    """
    raw_dir = PROJECT_ROOT / "data" / "news_dataset" / "raw"
    structured_dir = PROJECT_ROOT / "data" / "news_dataset" / "structured"

    raw_glob = f"{news_id_4}*.txt"
    structured_glob = f"{news_id_4}*.json"

    raw_path = _pick_single_match(raw_dir.glob(raw_glob), label="raw")
    structured_path = _pick_single_match(structured_dir.glob(structured_glob), label="structured")
    return raw_path, structured_path


def _resolve_raw_path_by_id(news_id_4: str) -> Path:
    """
    依 4 位數字新聞編號自動解析 raw 檔案路徑。

    Args:
        news_id_4: 4 位數字字串（例如 '0099'）。

    Returns:
        raw_path。
    """
    raw_dir = PROJECT_ROOT / "data" / "news_dataset" / "raw"
    raw_glob = f"{news_id_4}*.txt"
    return _pick_single_match(raw_dir.glob(raw_glob), label="raw")


def _build_structured_for_summary(
    raw_path: Path,
    *,
    max_retries: int,
) -> dict:
    """
    從 raw 檔案即時抽取結構化資料，供摘要流程使用。

    Args:
        raw_path: raw txt 檔案路徑。
        max_retries: LLM 呼叫重試次數。

    Returns:
        extract_schema 規格的 structured dict。
    """
    print("正在即時抽取結構化資料…", file=sys.stderr, flush=True)
    return extract_structured_from_raw(raw_path, max_retries=max_retries)


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="勞工新聞摘要生成（單篇）"
    )
    parser.add_argument(
        "news_id",
        nargs="?",
        default=None,
        help="新聞編號（1~4 位數字，例如 99 或 0099）。提供後可自動對應 raw/structured 並輸出至 outputs/",
    )
    parser.add_argument(
        "--rag",
        action="store_true",
        help="生成含 RAG 的摘要（news_id 模式下會輸出到 outputs/summary_XXXX_rag.md）",
    )
    parser.add_argument(
        "--structured-only",
        action="store_true",
        help="生成不含 RAG（僅 structured）的摘要（news_id 模式下會輸出到 outputs/summary_XXXX_structured_only.md）",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="生成僅基於 raw 原文、不含結構化資料與 RAG 的摘要（news_id 模式下會輸出到 outputs/summary_XXXX_raw.md）",
    )
    parser.add_argument(
        "--top-k", type=int, default=10,
        help="RAG 檢索 Top-k 法條數量（預設 10，--no-rag 時忽略）",
    )
    parser.add_argument(
        "--max-retries", type=int, default=3,
        help="LLM 呼叫最大重試次數（預設 3）",
    )

    args = parser.parse_args()

    if args.news_id is None:
        parser.error("必須提供新聞編號 news_id（例如：99 或 0099）")

    if not (args.rag or args.structured_only or args.raw_only):
        parser.error(
            "必須至少指定一個輸出版本：--rag、--structured-only、--raw-only "
            "（可同時指定多個，會各產一份）"
        )

    try:
        news_id_4 = _normalize_news_id(args.news_id)
        raw_path = _resolve_raw_path_by_id(news_id_4)
    except Exception as e:
        print(f"錯誤：{e}", file=sys.stderr)
        sys.exit(1)

    outputs_dir = PROJECT_ROOT / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 先執行 raw-only，再執行無 RAG（structured-only），最後執行含 RAG
        if args.raw_only:
            out_path = outputs_dir / f"summary_{news_id_4}_raw.md"
            summary = summarize_single_raw_only(
                raw_path,
                max_retries=args.max_retries,
            )
            out_path.write_text(summary, encoding="utf-8")
            print(f"摘要已寫入：{out_path}", file=sys.stderr)

        structured: dict | None = None
        if args.structured_only or args.rag:
            structured = _build_structured_for_summary(
                raw_path,
                max_retries=args.max_retries,
            )

        if args.structured_only:
            out_path = outputs_dir / f"summary_{news_id_4}_structured_only.md"
            summary = summarize_single(
                raw_path,
                structured,
                use_rag=False,
                top_k=args.top_k,
                max_retries=args.max_retries,
            )
            out_path.write_text(summary, encoding="utf-8")
            print(f"摘要已寫入：{out_path}", file=sys.stderr)

        if args.rag:
            out_path = outputs_dir / f"summary_{news_id_4}_rag.md"
            summary = summarize_single(
                raw_path,
                structured,
                use_rag=True,
                top_k=args.top_k,
                max_retries=args.max_retries,
            )
            out_path.write_text(summary, encoding="utf-8")
            print(f"摘要已寫入：{out_path}", file=sys.stderr)

    except Exception as e:
        print(f"錯誤：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
