#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ENV: Thesis
"""
單篇勞工新聞摘要生成腳本。

流程：讀取 raw 原文 + structured JSON → RAG 即時檢索相關法條 → LLM 生成摘要。

Usage:
    python src/scripts/summarize_news.py \
        --raw  data/news_dataset/raw/0221_xxx.txt \
        --structured data/news_dataset/structured/0221_xxx.json \
        [--out outputs/summary_0221.md] \
        [--top-k 10] \
        [--max-retries 3]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

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
from retrieval.retrieve import retrieve_laws_for_article

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
    structured_path: Path,
    top_k: int = 10,
    max_retries: int = 3,
) -> str:
    """
    對單篇新聞執行完整摘要流程：讀取 → RAG 檢索 → LLM 生成。

    Args:
        raw_path: raw txt 路徑。
        structured_path: structured JSON 路徑。
        top_k: RAG 檢索的 Top-k 法條數量。
        max_retries: LLM 呼叫重試次數。

    Returns:
        生成的摘要文字。
    """
    raw_text = _read_raw(raw_path)

    with open(structured_path, encoding="utf-8") as f:
        structured = json.load(f)

    print("正在檢索相關法條…", file=sys.stderr, flush=True)
    laws_text = retrieve_laws_for_article(structured, top_k=top_k)

    if not laws_text:
        print("[WARN] RAG 未檢索到任何法條。", file=sys.stderr)

    user_prompt = build_user_prompt(raw_text, structured, laws_text)

    print("正在呼叫 LLM 生成摘要…", file=sys.stderr, flush=True)
    summary = call_llm_for_summary(SYSTEM_PROMPT, user_prompt, max_retries=max_retries)

    return summary


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="勞工新聞摘要生成（單篇）"
    )
    parser.add_argument(
        "--raw", required=True,
        help="raw txt 檔案路徑",
    )
    parser.add_argument(
        "--structured", required=True,
        help="structured JSON 檔案路徑",
    )
    parser.add_argument(
        "--out", default=None,
        help="輸出路徑（若省略則輸出至 stdout）",
    )
    parser.add_argument(
        "--top-k", type=int, default=10,
        help="RAG 檢索 Top-k 法條數量（預設 10）",
    )
    parser.add_argument(
        "--max-retries", type=int, default=3,
        help="LLM 呼叫最大重試次數（預設 3）",
    )

    args = parser.parse_args()

    raw_path = Path(args.raw)
    structured_path = Path(args.structured)

    if not raw_path.exists():
        print(f"錯誤：raw 檔案不存在：{raw_path}", file=sys.stderr)
        sys.exit(1)
    if not structured_path.exists():
        print(f"錯誤：structured 檔案不存在：{structured_path}", file=sys.stderr)
        sys.exit(1)

    try:
        summary = summarize_single(
            raw_path, structured_path,
            top_k=args.top_k,
            max_retries=args.max_retries,
        )
    except Exception as e:
        print(f"錯誤：{e}", file=sys.stderr)
        sys.exit(1)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(summary, encoding="utf-8")
        print(f"摘要已寫入：{out_path}", file=sys.stderr)
    else:
        print(summary)


if __name__ == "__main__":
    main()
