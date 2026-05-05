#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step01：對 step00_db 每篇文章，用 summarize_news 核心流程生成兩份文本並寫回該篇目錄。

- summary_raw.txt：僅原文（與 summarize_single_raw_only 一致；讀取 original.txt）
- summary_structure.txt：structured-only（讀取 Step00 manifest 的 sources.structured JSON + original.txt）

依賴 .env 的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL（可用 --model 覆寫本次呼叫）。

Usage（專案根目錄）：
    python3 srcs/step01_generate_step00_summaries.py
    python3 srcs/step01_generate_step00_summaries.py --overwrite
    python3 srcs/step01_generate_step00_summaries.py --limit 2
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SRC_ROOT = PROJECT_ROOT / "srcs"
sys.path.insert(0, str(SRC_ROOT))

from scripts.summarize_news import (  # noqa: E402
    summarize_single,
    summarize_single_raw_only,
)


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _git_head() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT)
        ).decode("utf-8", errors="replace")
        return out.strip() or None
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Step01：step00_db 批量 summary_raw / summary_structure")
    parser.add_argument(
        "--db-root",
        type=Path,
        default=PROJECT_ROOT
        / "intermediate"
        / "step00_sampling"
        / "step00_db_deepseek-v3",
    )
    parser.add_argument(
        "--sampled-json",
        type=Path,
        default=PROJECT_ROOT
        / "intermediate"
        / "step00_sampling"
        / "step00_sampled_articles_30.json",
        help="內含 sequence（news_id 列表）的 Step00 manifest",
    )
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="覆寫 LLM 模型名（預設取自環境變數 LLM_MODEL）",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="已存在 summary_raw.txt / summary_structure.txt 仍重算",
    )
    parser.add_argument("--limit", type=int, default=None, help="只處理前 N 篇（除錯）")
    args = parser.parse_args()

    db_root: Path = args.db_root
    articles_root = db_root / "articles"
    if not articles_root.is_dir():
        print(f"錯誤：{articles_root} 不存在", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(args.sampled_json.read_text(encoding="utf-8"))
    sequence: list[str] = manifest["sequence"]
    by_nid = {it["news_id"]: it for it in manifest.get("items", [])}
    if args.limit is not None:
        sequence = sequence[: args.limit]

    started = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    n_ok = 0

    for nid in sequence:
        adir = articles_root / nid
        original_path = adir / "original.txt"
        struct_local = adir / "structured.json"
        src_struct = (by_nid.get(nid) or {}).get("sources", {}).get("structured")
        if struct_local.is_file():
            struct_path = struct_local
        elif src_struct:
            struct_path = PROJECT_ROOT / src_struct
        else:
            struct_path = struct_local

        out_raw = adir / "summary_raw.txt"
        out_struct = adir / "summary_structure.txt"

        rec: dict[str, Any] = {
            "news_id": nid,
            "article_dir": str(adir.relative_to(PROJECT_ROOT)),
            "ok": False,
            "error": None,
            "summary_raw_written": False,
            "summary_structure_written": False,
            "skipped": False,
        }

        if not original_path.is_file() or not struct_path.is_file():
            rec["error"] = "缺少 original.txt 或 structured 來源（manifest.sources.structured）"
            records.append(rec)
            continue

        try:
            need_raw = args.overwrite or not out_raw.is_file()
            need_struct = args.overwrite or not out_struct.is_file()
            if not need_raw and not need_struct:
                rec["skipped"] = True
                rec["ok"] = True
                n_ok += 1
                records.append(rec)
                continue

            structured = json.loads(struct_path.read_text(encoding="utf-8"))

            if need_raw:
                raw_summary = summarize_single_raw_only(
                    original_path,
                    max_retries=args.max_retries,
                    model=args.model,
                )
                out_raw.write_text(raw_summary.strip() + "\n", encoding="utf-8", newline="\n")
                rec["summary_raw_written"] = True

            if need_struct:
                st_summary = summarize_single(
                    original_path,
                    structured,
                    use_rag=False,
                    top_k=10,
                    max_retries=args.max_retries,
                    model=args.model,
                )
                out_struct.write_text(st_summary.strip() + "\n", encoding="utf-8", newline="\n")
                rec["summary_structure_written"] = True

            rec["ok"] = True
            n_ok += 1
            print(f"[OK] {nid}", file=sys.stderr, flush=True)
        except Exception as e:
            rec["error"] = str(e)
            print(f"[FAIL] {nid}: {e}", file=sys.stderr, flush=True)

        records.append(rec)

    finished = datetime.now(timezone.utc).isoformat()

    exp_dir = PROJECT_ROOT / "experiment"
    exp_dir.mkdir(parents=True, exist_ok=True)
    exp_path = exp_dir / f"step01_summaries_run_{_utc_ts()}.json"
    exp_path.write_text(
        json.dumps(
            {
                "step": "step01",
                "kind": "step00_db_summaries",
                "script": "srcs/step01_generate_step00_summaries.py",
                "underlying": "srcs/scripts/summarize_news.py",
                "git_head": _git_head(),
                "db_root": str(db_root.relative_to(PROJECT_ROOT)),
                "sampled_json": str(args.sampled_json.relative_to(PROJECT_ROOT)),
                "model": args.model,
                "overwrite": args.overwrite,
                "limit": args.limit,
                "started_at_utc": started,
                "finished_at_utc": finished,
                "n_articles": len(sequence),
                "n_ok": n_ok,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"experiment: {exp_path}", file=sys.stderr)
    if n_ok < len(sequence):
        sys.exit(1)


if __name__ == "__main__":
    main()
