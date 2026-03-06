#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ENV: Thesis
"""
結構化抽取腳本。

支援單篇與批量模式：
  單篇：python extract_structured.py single <file>
  # 批量模式：依次處理多篇文件
  # 用法：python extract_structured.py batch [-c 5] [-r 3] [-n 10]
  #   -c：同時處理（執行緒）數，預設 5
  #   -r：每篇最多重試次數，預設 3
  #   -n：最多處理檔案數，預設 10

批量模式自動跳過已完成檔案（斷點續跑），失敗記錄寫入 logs/extract_errors.log。
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

API_KEY = os.environ["LLM_API_KEY"]
MODEL = os.environ.get("LLM_MODEL", "deepseek-v3")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from openai import OpenAI

from prompts.extract_structured import SYSTEM_PROMPT, build_user_prompt
from scripts.parse_raw_metadata import parse_raw_metadata

RAW_DIR = PROJECT_ROOT / "data" / "news_dataset" / "raw"
OUT_DIR = PROJECT_ROOT / "data" / "news_dataset" / "structured"
LOG_DIR = PROJECT_ROOT / "logs"

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """取得共用的 OpenAI client（thread-safe，內部自帶 connection pool）。"""
    global _client
    if _client is None:
        _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


def _setup_logger() -> logging.Logger:
    """設定 error logger，寫入 logs/extract_errors.log。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("extract_structured")
    logger.setLevel(logging.WARNING)
    if not logger.handlers:
        fh = logging.FileHandler(LOG_DIR / "extract_errors.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(fh)
    return logger


logger = _setup_logger()


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


def _strip_json_comments(s: str) -> str:
    """
    移除 LLM 可能輸出的 JSON 內 // 單行註解，並刪除因此產生的尾隨逗號。
    不處理字串內容內的 //（依該行雙引號奇偶判斷是否在字串中）。
    """
    lines: list[str] = []
    for line in s.split("\n"):
        in_string = False
        i = 0
        while i < len(line):
            if line[i] == "\\" and in_string and i + 1 < len(line):
                i += 2
                continue
            if line[i] == '"':
                in_string = not in_string
                i += 1
                continue
            if not in_string and i + 1 < len(line) and line[i : i + 2] == "//":
                line = line[:i].rstrip()
                break
            i += 1
        lines.append(line)
    # 移除尾隨逗號（JSON 不允許 , } 或 , ]）
    joined = "\n".join(lines)
    joined = re.sub(r",(\s*[}\]])", r"\1", joined)
    return joined


def call_llm(user_prompt: str, max_retries: int = 3) -> dict:
    """
    調用 LLM API 進行結構化抽取，含 exponential backoff 重試。

    Args:
        user_prompt: 組裝好的 user prompt。
        max_retries: 最大重試次數。

    Returns:
        LLM 輸出的 dict。

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
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )

            raw_json = response.choices[0].message.content or ""
            stripped = re.sub(r"^```(?:json)?\s*\n?", "", raw_json.strip())
            stripped = re.sub(r"\n?```\s*$", "", stripped).strip()
            stripped = _strip_json_comments(stripped)
            return json.loads(stripped)

        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"LLM 輸出非合法 JSON: {e}\n---\n{raw_json[:500]}"
            )
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)
                time.sleep(wait)

    raise RuntimeError(f"API 調用失敗（已重試 {max_retries} 次）: {last_error}")


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


def extract_single(
    raw_path: Path, dry_run: bool = False, max_retries: int = 3
) -> bool:
    """
    處理單篇 raw 檔案。

    Args:
        raw_path: raw txt 檔案路徑。
        dry_run: 若 True 則僅輸出解析結果與 prompt，不調用 LLM。
        max_retries: LLM API 重試次數。

    Returns:
        是否成功。
    """
    content = raw_path.read_text(encoding="utf-8")

    meta = parse_raw_metadata(content)
    if not meta:
        logger.warning("SKIP (metadata parse failed): %s", raw_path.name)
        return False

    parsed = parse_raw_content(content, raw_path.name)
    if not parsed["body"]:
        logger.warning("SKIP (no body): %s", raw_path.name)
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

    llm_result = call_llm(user_prompt, max_retries=max_retries)
    result = merge_result(llm_result, meta.to_dict(), parsed)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_name = raw_path.stem + ".json"
    out_path = OUT_DIR / out_name
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True


def _process_one(raw_path: Path, max_retries: int) -> tuple[str, bool, str]:
    """
    Thread worker：處理單篇並回傳結果。

    Args:
        raw_path: raw txt 路徑。
        max_retries: 重試次數。

    Returns:
        (檔名, 是否成功, 錯誤訊息)。
    """
    try:
        ok = extract_single(raw_path, max_retries=max_retries)
        return (raw_path.name, ok, "" if ok else "skipped")
    except Exception as e:
        logger.error("FAIL: %s | %s", raw_path.name, e)
        return (raw_path.name, False, str(e))


def run_batch(
    concurrency: int = 5, max_retries: int = 3, limit: int | None = None
) -> None:
    """
    批量處理 raw 檔案，自動跳過已完成。

    Args:
        concurrency: 並行數量。
        max_retries: 每篇重試次數。
        limit: 最多處理篇數；None 表示不限制。
    """
    all_raw = sorted(RAW_DIR.glob("*.txt"))
    done_stems = {p.stem for p in OUT_DIR.glob("*.json")} if OUT_DIR.exists() else set()
    todo = [f for f in all_raw if f.stem not in done_stems]
    if limit is not None:
        todo = todo[:limit]

    print(f"總計 {len(all_raw)} 篇，已完成 {len(done_stems)} 篇，待處理 {len(todo)} 篇", flush=True)
    print(f"並行數: {concurrency} | 重試次數: {max_retries}", flush=True)
    print("-" * 60, flush=True)

    if not todo:
        print("全部已完成，無需處理。")
        return

    t0 = time.time()
    ok_count = 0
    fail_count = 0
    skip_count = 0

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_process_one, f, max_retries): f for f in todo
        }

        for i, future in enumerate(as_completed(futures), 1):
            name, success, err = future.result()
            elapsed = time.time() - t0

            if success:
                ok_count += 1
                status = "OK"
            elif err == "skipped":
                skip_count += 1
                status = "SKIP"
            else:
                fail_count += 1
                status = f"FAIL: {err[:80]}"

            avg = elapsed / i
            eta = avg * (len(todo) - i)
            eta_m, eta_s = divmod(int(eta), 60)
            eta_h, eta_m = divmod(eta_m, 60)

            print(
                f"[{i}/{len(todo)}] {status} | {name[:50]}"
                f" | ETA {eta_h:02d}:{eta_m:02d}:{eta_s:02d}",
                flush=True,
            )

    total_time = time.time() - t0
    m, s = divmod(int(total_time), 60)
    h, m = divmod(m, 60)

    print("=" * 60)
    print(f"完成！耗時 {h:02d}:{m:02d}:{s:02d}")
    print(f"成功: {ok_count} | 跳過: {skip_count} | 失敗: {fail_count}")

    if fail_count > 0:
        print(f"失敗記錄見 {LOG_DIR / 'extract_errors.log'}")


def main() -> None:
    """CLI 入口，支援 single / batch 子命令。"""
    parser = argparse.ArgumentParser(
        description="勞工新聞結構化特徵抽取（單篇 / 批量）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # single 子命令
    sp_single = sub.add_parser("single", help="處理單篇 raw 檔案")
    sp_single.add_argument("file", help="raw txt 檔案路徑")
    sp_single.add_argument("--dry-run", action="store_true", help="僅預覽，不調用 LLM")

    # batch 子命令
    sp_batch = sub.add_parser("batch", help="批量處理所有 raw 檔案（自動跳過已完成）")
    sp_batch.add_argument(
        "-c", "--concurrency", type=int, default=10,
        help="並行數量（預設 10）",
    )
    sp_batch.add_argument(
        "-r", "--retry", type=int, default=3,
        help="每篇最大重試次數（預設 3）",
    )
    sp_batch.add_argument(
        "-n", "--limit", type=int, default=None,
        help="最多處理篇數（預設不限制）",
    )

    args = parser.parse_args()

    if args.command == "single":
        raw_path = Path(args.file)
        if not raw_path.exists():
            print(f"檔案不存在: {raw_path}")
            sys.exit(1)
        success = extract_single(raw_path, dry_run=args.dry_run)
        if success:
            print(f"OK: {raw_path.name}")
        if not success:
            sys.exit(1)

    elif args.command == "batch":
        run_batch(
            concurrency=args.concurrency,
            max_retries=args.retry,
            limit=args.limit,
        )


if __name__ == "__main__":
    main()
