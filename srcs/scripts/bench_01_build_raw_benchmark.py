#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bench01：對 raw 新聞前 N 則產出 gpt-4o 偽參考摘要（與 RAG 管線隔離）。

不依賴 structured / Chroma / retrieve；僅複用 raw-only prompt 與 OpenAI SDK 呼叫型式。
LLM_BASE_URL、LLM_API_KEY 與主專案相同（.env）；本腳本僅將 model 固定為 gpt-4o（中介路由）。

產出目錄：`intermediate/benchmark_bench01/`（與 `intermediate/outputs/` 的一般摘要分開）。

Usage（專案根目錄）:
    python3 srcs/scripts/bench_01_build_raw_benchmark.py
    python3 srcs/scripts/bench_01_build_raw_benchmark.py --limit 10
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SRC_ROOT = PROJECT_ROOT / "srcs"
sys.path.insert(0, str(SRC_ROOT))

from openai import OpenAI

from config.paths import NEWS_RAW_DIR
from prompts.summary_prompt_raw_only import (
    SYSTEM_PROMPT_RAW_ONLY,
    build_user_prompt_raw_only,
)

# 與 summarize_news.py 對齊：中介同一套 URL / KEY；bench 僅換 model 名
API_KEY = os.environ["LLM_API_KEY"]
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
BENCHMARK_MODEL = "gpt-4o"


def _read_raw(raw_path: Path) -> str:
    content = raw_path.read_text(encoding="utf-8")
    title_m = re.search(r"【標題】\s*\n(.+?)(?=\n\s*【)", content, re.DOTALL)
    body_m = re.search(r"【內文】\s*\n(.+)", content, re.DOTALL)
    title = title_m.group(1).strip() if title_m else ""
    body = body_m.group(1).strip() if body_m else content.strip()
    if title:
        return f"{title}\n\n{body}"
    return body


def _strip_md_fences(text: str) -> str:
    text = re.sub(r"^```(?:markdown)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text).strip()
    return text


def _safe_slug(stem: str, max_len: int = 80) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", stem, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:max_len] or "article").rstrip("_")


def call_benchmark_llm(
    client: OpenAI,
    *,
    model: str,
    raw_text: str,
    max_retries: int,
) -> str:
    user_prompt = build_user_prompt_raw_only(raw_text)
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_RAW_ONLY},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
            )
            text = response.choices[0].message.content or ""
            return _strip_md_fences(text)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)
                print(
                    f"[WARN] LLM 失敗（{attempt + 1}/{max_retries + 1}），{wait}s 後重試：{e}",
                    file=sys.stderr,
                )
                time.sleep(wait)
    raise RuntimeError(f"LLM 呼叫失敗：{last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="bench01：raw 前 N 則 gpt-4o 偽參考摘要")
    parser.add_argument("--limit", type=int, default=10, help="處理篇數（預設 10）")
    parser.add_argument(
        "--max-retries", type=int, default=3, help="單篇 LLM 重試次數（預設 3）"
    )
    args = parser.parse_args()

    model = BENCHMARK_MODEL

    raw_dir = NEWS_RAW_DIR
    if not raw_dir.is_dir():
        print(f"錯誤：raw 目錄不存在：{raw_dir}", file=sys.stderr)
        sys.exit(1)

    all_txt = sorted(raw_dir.glob("*.txt"))
    if not all_txt:
        print(f"錯誤：{raw_dir} 下沒有 .txt", file=sys.stderr)
        sys.exit(1)

    batch = all_txt[: args.limit]
    started = datetime.now(timezone.utc).isoformat()

    # bench 參考摘要與 manifest 同屬 benchmark_bench01；一般摘要仍由 summarize_news 寫入 OUTPUTS_DIR
    bench_dir = PROJECT_ROOT / "intermediate" / "benchmark_bench01"
    exp_dir = PROJECT_ROOT / "experiment"
    for d in (bench_dir, exp_dir):
        d.mkdir(parents=True, exist_ok=True)

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    manifest_items: list[dict[str, Any]] = []
    run_records: list[dict[str, Any]] = []

    for i, raw_path in enumerate(batch, start=1):
        idx_tag = f"{i:02d}"
        slug = _safe_slug(raw_path.stem)
        out_name = f"bench01_{idx_tag}_{slug}_reference.md"
        out_path = bench_dir / out_name
        rec: dict[str, Any] = {
            "seq": i,
            "source_file": str(raw_path.relative_to(PROJECT_ROOT)),
            "output_file": str(out_path.relative_to(PROJECT_ROOT)),
            "model": model,
            "base_url": BASE_URL,
            "ok": False,
            "error": None,
        }
        try:
            raw_text = _read_raw(raw_path)
            summary = call_benchmark_llm(
                client,
                model=model,
                raw_text=raw_text,
                max_retries=args.max_retries,
            )
            header = (
                f"<!-- bench01 | model={model} | source={raw_path.name} | seq={i} -->\n\n"
            )
            out_path.write_text(header + summary + "\n", encoding="utf-8")
            rec["ok"] = True
            print(f"[OK] {i}/{len(batch)} -> {out_path.name}", file=sys.stderr)
        except Exception as e:
            rec["error"] = str(e)
            print(f"[FAIL] {raw_path.name}: {e}", file=sys.stderr)

        manifest_items.append(
            {
                "seq": i,
                "raw_stem": raw_path.stem,
                "raw_path": str(raw_path.relative_to(PROJECT_ROOT)),
                "reference_md": str(out_path.relative_to(PROJECT_ROOT))
                if rec["ok"]
                else None,
                "ok": rec["ok"],
                "error": rec["error"],
            }
        )
        run_records.append(rec)

    finished = datetime.now(timezone.utc).isoformat()

    manifest = {
        "step": "bench01",
        "model": model,
        "base_url": BASE_URL,
        "limit": args.limit,
        "started_at_utc": started,
        "finished_at_utc": finished,
        "items": manifest_items,
    }
    manifest_path = bench_dir / "bench01_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    exp_path = exp_dir / f"bench01_run_{ts}.json"
    exp_path.write_text(
        json.dumps(
            {
                "step": "bench01",
                "script": "src/scripts/bench_01_build_raw_benchmark.py",
                "prompt_module": "src/prompts/summary_prompt_raw_only.py",
                "model": model,
                "base_url": BASE_URL,
                "started_at_utc": started,
                "finished_at_utc": finished,
                "records": run_records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"manifest: {manifest_path}", file=sys.stderr)
    print(f"experiment: {exp_path}", file=sys.stderr)

    n_ok = sum(1 for r in run_records if r.get("ok"))
    if n_ok == 0 and batch:
        print("錯誤：本篇次全部失敗，請檢查 .env 的 LLM_API_KEY、LLM_BASE_URL 與中介是否支援 gpt-4o。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
