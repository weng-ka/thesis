#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step01：依 Step00 MVP「1.1 Google Sheet 資料表（最小欄位）」匯出 CSV，對應 step00_db 內文章。

欄位：article_id, raw_title, raw_text, summary_raw, summary_structured, summary_rag

- raw_title / 追溯用結構化：讀 manifest items[].sources.structured
- 其餘正文：讀 articles/<id>/ 下 original.txt 與三份 summary_*.txt

Usage（專案根目錄）：
    python3 srcs/step01_export_google_sheet_csv.py
    python3 srcs/step01_export_google_sheet_csv.py --out intermediate/step01_platform/step01_google_sheet_articles_30.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent


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


def _title_from_structured(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data.get("metadata") or {}
    title = (meta.get("title") or "").strip()
    return title


def main() -> None:
    parser = argparse.ArgumentParser(description="匯出 Google Sheet 最小欄位 CSV（30 篇）")
    parser.add_argument(
        "--sampled-json",
        type=Path,
        default=PROJECT_ROOT
        / "intermediate"
        / "step00_sampling"
        / "step00_sampled_articles_30.json",
    )
    parser.add_argument(
        "--db-root",
        type=Path,
        default=PROJECT_ROOT
        / "intermediate"
        / "step00_sampling"
        / "step00_db_deepseek-v3",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=PROJECT_ROOT
        / "intermediate"
        / "step01_platform"
        / "step01_google_sheet_articles_30.csv",
    )
    args = parser.parse_args()

    manifest = json.loads(args.sampled_json.read_text(encoding="utf-8"))
    sequence: list[str] = manifest["sequence"]
    by_nid = {it["news_id"]: it for it in manifest.get("items", [])}

    articles_root = args.db_root / "articles"
    if not articles_root.is_dir():
        print(f"錯誤：{articles_root} 不存在", file=sys.stderr)
        sys.exit(1)

    args.out.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "article_id",
        "raw_title",
        "raw_text",
        "summary_raw",
        "summary_structured",
        "summary_rag",
    ]

    started = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []

    for nid in sequence:
        adir = articles_root / nid
        item = by_nid.get(nid) or {}
        src_struct = (item.get("sources") or {}).get("structured")
        if not src_struct:
            warnings.append(f"{nid}: manifest 缺少 sources.structured")
            title = ""
        else:
            sp = PROJECT_ROOT / src_struct
            if not sp.is_file():
                warnings.append(f"{nid}: structured 檔不存在 {src_struct}")
                title = ""
            else:
                title = _title_from_structured(sp)

        def read_txt(name: str) -> str:
            p = adir / name
            if not p.is_file():
                warnings.append(f"{nid}: 缺少 {name}")
                return ""
            return p.read_text(encoding="utf-8")

        row = {
            "article_id": nid,
            "raw_title": title,
            "raw_text": read_txt("original.txt"),
            "summary_raw": read_txt("summary_raw.txt"),
            "summary_structured": read_txt("summary_structure.txt"),
            "summary_rag": read_txt("summary_rag.txt"),
        }
        rows.append(row)

    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            quoting=csv.QUOTE_MINIMAL,
        )
        w.writeheader()
        w.writerows(rows)

    finished = datetime.now(timezone.utc).isoformat()

    exp_dir = PROJECT_ROOT / "experiment"
    exp_dir.mkdir(parents=True, exist_ok=True)
    exp_path = exp_dir / f"step01_google_sheet_csv_run_{_utc_ts()}.json"
    exp_path.write_text(
        json.dumps(
            {
                "step": "step01",
                "kind": "google_sheet_csv_export",
                "script": "srcs/step01_export_google_sheet_csv.py",
                "spec_ref": "docs/notes/Step00_人工實驗平台網站製作計劃_MVP.md §1.1",
                "git_head": _git_head(),
                "sampled_json": str(args.sampled_json.relative_to(PROJECT_ROOT)),
                "db_root": str(args.db_root.relative_to(PROJECT_ROOT)),
                "out_csv": str(args.out.relative_to(PROJECT_ROOT)),
                "n_rows": len(rows),
                "warnings": warnings,
                "started_at_utc": started,
                "finished_at_utc": finished,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"[OK] {args.out} ({len(rows)} rows)", file=sys.stderr)
    print(f"[OK] experiment: {exp_path}", file=sys.stderr)
    if warnings:
        print(f"[WARN] {len(warnings)} 則警告", file=sys.stderr)


if __name__ == "__main__":
    main()
