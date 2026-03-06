#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ENV: Thesis
"""
結構化抽取腳本。

對 data/news_dataset/raw 中的單篇新聞文本，
調用 LLM 進行結構化特徵抽取，輸出至 data/news_dataset/structured。
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

API_KEY = os.environ["LLM_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "deepseek-v3")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from prompts.extract_structured import SYSTEM_PROMPT, build_user_prompt
from scripts.parse_raw_metadata import parse_raw_metadata

RAW_DIR = PROJECT_ROOT / "data" / "news_dataset" / "raw"
OUT_DIR = PROJECT_ROOT / "data" / "news_dataset" / "structured"


def parse_raw_content(content: str, filename: str) -> dict:
    """
    從 raw txt 內容解析標題、正文，並從檔名生成 identifier。

    Args:
        content: 完整 raw txt 內容。
        filename: raw 檔案名稱（如 "0221_店铺注销了 谁对劳动者负责_.txt"）。

    Returns:
        dict with keys: title, body, identifier.
    """
    title_match = re.search(r"【標題】\s*\n(.+?)(?=\n\s*【)", content, re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""

    body_match = re.search(r"【內文】\s*\n(.+)", content, re.DOTALL)
    body = body_match.group(1).strip() if body_match else ""

    prefix_match = re.match(r"^(\d+)", filename)
    identifier = f"NEWS-{prefix_match.group(1)}" if prefix_match else ""

    return {"title": title, "body": body, "identifier": identifier}


def call_llm(user_prompt: str) -> dict:
    """
    調用 LLM API 進行結構化抽取。

    Args:
        user_prompt: 組裝好的 user prompt。

    Returns:
        LLM 輸出的 dict。

    Raises:
        ValueError: API key 未設定。
        RuntimeError: API 調用或 JSON 解析失敗。
    """
    if API_KEY == "YOUR_API_KEY_HERE":
        raise ValueError("請先在腳本頂部填入 API_KEY")

    from openai import OpenAI

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    raw_json = response.choices[0].message.content or ""
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", raw_json.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM 輸出非合法 JSON: {e}\n---\n{raw_json[:500]}")


def merge_result(llm_result: dict, meta_dict: dict, parsed: dict) -> dict:
    """
    合併 LLM 輸出與程式預填的 metadata。

    Args:
        llm_result: LLM 輸出的 dict（不含 metadata）。
        meta_dict: parse_raw_metadata 取得的 {date, source, author}。
        parsed: parse_raw_content 取得的 {url, title, body, identifier}。

    Returns:
        完整結構化 JSON dict。
    """
    metadata = {
        "title": parsed["title"],
        "author": meta_dict["author"],
        "date": meta_dict["date"],
        "source": meta_dict["source"],
        "identifier": parsed["identifier"],
    }

    return {
        "metadata": metadata,
        "5W1H": llm_result.get("5W1H", {}),
        "themes": llm_result.get("themes", []),
        "events": llm_result.get("events", []),
    }


def extract_single(raw_path: Path, dry_run: bool = False) -> bool:
    """
    處理單篇 raw 檔案。

    Args:
        raw_path: raw txt 檔案路徑。
        dry_run: 若 True 則僅輸出解析結果與 prompt，不調用 LLM。

    Returns:
        是否成功。
    """
    content = raw_path.read_text(encoding="utf-8")

    meta = parse_raw_metadata(content)
    if not meta:
        print(f"SKIP (metadata parse failed): {raw_path.name}")
        return False

    parsed = parse_raw_content(content, raw_path.name)
    if not parsed["body"]:
        print(f"SKIP (no body): {raw_path.name}")
        return False

    user_prompt = build_user_prompt(title=parsed["title"], body=parsed["body"])

    if dry_run:
        print(f"{'=' * 60}")
        print(f"FILE: {raw_path.name}")
        print(f"{'=' * 60}")
        print(f"Title:      {parsed['title'][:80]}")
        print(f"Identifier: {parsed['identifier']}")
        print(f"Date:       {meta.date}")
        print(f"Source:     {meta.source}")
        print(f"Author:     {meta.author}")
        print(f"Body:       {len(parsed['body'])} chars")
        print(f"{'- ' * 30}")
        print("USER PROMPT:")
        print(user_prompt[:600])
        if len(user_prompt) > 600:
            print(f"  ... ({len(user_prompt)} chars total)")
        print()
        return True

    llm_result = call_llm(user_prompt)
    result = merge_result(llm_result, meta.to_dict(), parsed)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_name = raw_path.stem + ".json"
    out_path = OUT_DIR / out_name
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OK: {out_path}")
    return True


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="對單篇 raw 新聞文本進行結構化特徵抽取"
    )
    parser.add_argument(
        "file",
        help="raw txt 檔案路徑（如 data/news_dataset/raw/0001_xxx.txt）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="僅解析並預覽 prompt，不調用 LLM",
    )
    args = parser.parse_args()

    raw_path = Path(args.file)
    if not raw_path.exists():
        print(f"檔案不存在: {raw_path}")
        sys.exit(1)

    success = extract_single(raw_path, dry_run=args.dry_run)
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
