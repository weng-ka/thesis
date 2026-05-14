#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step01d（GH Pages 友善）：匯出前端可直接讀取的靜態資料（避免 CORS / Apps Script query/path 限制）。

輸出（預設寫到 step01_platform_web/public/step01_data/）：
- step01_articles_by_id.json：article_id -> { raw_title, raw_text, summary_raw, summary_structured, summary_rag }
- step01_sessions_10x12.json：session_id -> [article_id x 12]

文章五個文字欄位（raw_title / raw_text / summary_*）在寫入 JSON 前會經 OpenCC `t2s` 轉為簡體（未安裝 opencc 則略過並於 stderr 提示）。

注意：A/B/C 置換（perm）由前端每次載入 session 時隨機生成，並在提交 payload 內回傳 ab_mapping，
後端即可反解版本（raw/structured/rag）。

Usage（專案根目錄）：
  python3 srcs/step01_export_web_static_data.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from opencc import OpenCC

    _T2S = OpenCC("t2s")
except ImportError:  # pragma: no cover
    _T2S = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _t2s_text(s: str) -> str:
    """繁體→簡體（OpenCC）；未安裝 opencc 時原樣返回。"""
    if _T2S is None:
        return s
    return _T2S.convert(s)


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git_head() -> str | None:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT))
        return out.decode("utf-8", errors="replace").strip() or None
    except Exception:
        return None


def main() -> None:
    p = argparse.ArgumentParser(description="匯出 step01_platform_web 靜態資料（sessions + articles）")
    p.add_argument(
        "--sessions-json",
        type=Path,
        default=PROJECT_ROOT / "intermediate" / "step00_sampling" / "step00_sessions_10x12.json",
    )
    p.add_argument(
        "--articles-csv",
        type=Path,
        default=PROJECT_ROOT / "intermediate" / "step01_platform" / "step01_google_sheet_articles_30.csv",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / "step01_platform_web" / "public" / "step01_data",
    )
    args = p.parse_args()

    sessions = json.loads(args.sessions_json.read_text(encoding="utf-8"))
    sessions_map: dict[str, list[str]] = sessions["sessions"]

    # CSV 直接用最保守的 parse（避免 pandas 依賴）
    import csv

    rows: dict[str, dict[str, Any]] = {}
    with args.articles_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            aid = (r.get("article_id") or "").strip()
            if not aid:
                continue
            rows[aid] = {
                "article_id": aid,
                "raw_title": _t2s_text(r.get("raw_title") or ""),
                "raw_text": _t2s_text(r.get("raw_text") or ""),
                "summary_raw": _t2s_text(r.get("summary_raw") or ""),
                "summary_structured": _t2s_text(r.get("summary_structured") or ""),
                "summary_rag": _t2s_text(r.get("summary_rag") or ""),
            }

    # 確保 sessions 內的 id 都存在於 CSV
    missing: list[str] = []
    for sid, ids in sessions_map.items():
        for aid in ids:
            if aid not in rows:
                missing.append(f"{sid}:{aid}")
    if missing:
        raise SystemExit(f"錯誤：sessions 內出現不在 CSV 的 article_id（前 10 筆）：{missing[:10]}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_articles = args.out_dir / "step01_articles_by_id.json"
    out_sessions = args.out_dir / "step01_sessions_10x12.json"

    if _T2S is None:
        print(
            "[WARN] 未安裝 opencc-python-reimplemented，文章欄位未做繁→簡（pip install opencc-python-reimplemented）",
            file=sys.stderr,
        )

    out_articles.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    out_sessions.write_text(
        json.dumps(
            {
                "step": "step01",
                "kind": "sessions",
                "data_version": "step00_sessions_10x12_v1",
                "sessions": sessions_map,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # experiment run record
    ts = _utc_ts()
    rec = {
        "step": "step01",
        "kind": "export_web_static_data",
        "script": "srcs/step01_export_web_static_data.py",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "inputs": {
            "sessions_json": str(args.sessions_json.relative_to(PROJECT_ROOT)),
            "articles_csv": str(args.articles_csv.relative_to(PROJECT_ROOT)),
        },
        "outputs": {
            "articles_by_id": str(out_articles.relative_to(PROJECT_ROOT)),
            "sessions": str(out_sessions.relative_to(PROJECT_ROOT)),
        },
    }
    (PROJECT_ROOT / "experiment").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "experiment" / f"step01_platform_static_data_run_{ts}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"OK: wrote {out_articles} and {out_sessions}")


if __name__ == "__main__":
    main()

