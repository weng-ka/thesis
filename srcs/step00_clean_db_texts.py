#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step00 後處理：清理 step00_db 內每篇文章的 original / summary_rag 文本。

- summary_rag.txt：移除開頭 HTML 註解區塊 <!-- ... -->（可跨行），並統一換行為 LF。
- original.txt：只保留「【內文】」標題之後的正文（若無則嘗試「【内文】」），統一換行為 LF。

Usage（專案根目錄）：
    python3 srcs/step00_clean_db_texts.py
    python3 srcs/step00_clean_db_texts.py --db-root intermediate/step00_sampling/step00_db_deepseek-v3
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent

BODY_MARKERS = ("【內文】", "【内文】")
RAG_COMMENT_RE = re.compile(r"^\s*<!--.*?-->\s*", re.DOTALL)


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


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _strip_rag_header(text: str) -> str:
    text = _normalize_newlines(text)
    text = RAG_COMMENT_RE.sub("", text, count=1)
    return text.lstrip("\n")


def _extract_raw_body(text: str) -> tuple[str, str | None]:
    """有標題區塊時取【內文】後；已清理過、全檔即正文時整段保留（冪等）。"""
    text = _normalize_newlines(text)
    for marker in BODY_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            rest = text[idx + len(marker) :]
            rest = rest.lstrip("\n").strip("\n")
            return rest, marker
    return text.strip("\n"), None


def main() -> None:
    parser = argparse.ArgumentParser(description="清理 step00_db 的 raw / rag 文本")
    parser.add_argument(
        "--db-root",
        type=Path,
        default=PROJECT_ROOT
        / "intermediate"
        / "step00_sampling"
        / "step00_db_deepseek-v3",
        help="step00 資料庫根目錄",
    )
    args = parser.parse_args()

    db_root: Path = args.db_root
    articles_root = db_root / "articles"
    if not articles_root.is_dir():
        raise SystemExit(f"articles 目錄不存在：{articles_root}")

    started = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []

    for article_dir in sorted(articles_root.iterdir(), key=lambda p: p.name):
        if not article_dir.is_dir():
            continue
        nid = article_dir.name
        original_path = article_dir / "original.txt"
        summary_rag_path = article_dir / "summary_rag.txt"
        rec: dict[str, Any] = {
            "news_id": nid,
            "original_path": str(original_path.relative_to(PROJECT_ROOT)),
            "summary_rag_path": str(summary_rag_path.relative_to(PROJECT_ROOT)),
            "original_changed": False,
            "summary_rag_changed": False,
            "original_body_marker": None,
            "warnings": [],
        }

        if original_path.is_file():
            raw_in = original_path.read_text(encoding="utf-8")
            body, marker = _extract_raw_body(raw_in)
            if marker is None and any(m in raw_in for m in BODY_MARKERS):
                rec["warnings"].append("original 含異常標記片段但未切出內文，請手動檢查")
            elif marker is None:
                rec["original_body_marker"] = None
            else:
                rec["original_body_marker"] = marker
            raw_out = body + "\n"
            raw_in_norm = _normalize_newlines(raw_in)
            if raw_in_norm != raw_out:
                original_path.write_text(raw_out, encoding="utf-8", newline="\n")
                rec["original_changed"] = True
        else:
            rec["warnings"].append("缺少 original.txt")

        if summary_rag_path.is_file():
            rag_in = summary_rag_path.read_text(encoding="utf-8")
            rag_out = _strip_rag_header(rag_in).strip("\n") + "\n"
            rag_in_norm = _normalize_newlines(rag_in)
            if rag_in_norm != rag_out:
                summary_rag_path.write_text(rag_out, encoding="utf-8", newline="\n")
                rec["summary_rag_changed"] = True
        else:
            rec["warnings"].append("缺少 summary_rag.txt")

        records.append(rec)

    finished = datetime.now(timezone.utc).isoformat()

    exp_dir = PROJECT_ROOT / "experiment"
    exp_dir.mkdir(parents=True, exist_ok=True)
    exp_path = exp_dir / f"step00_db_clean_run_{_utc_ts()}.json"
    exp_path.write_text(
        json.dumps(
            {
                "step": "step00_db_clean",
                "script": "srcs/step00_clean_db_texts.py",
                "git_head": _git_head(),
                "db_root": str(db_root.relative_to(PROJECT_ROOT)),
                "article_count": len(records),
                "started_at_utc": started,
                "finished_at_utc": finished,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    n_orig = sum(1 for r in records if r.get("original_changed"))
    n_sr = sum(1 for r in records if r.get("summary_rag_changed"))
    print(f"[OK] 處理 {len(records)} 篇；original 變更 {n_orig}；summary_rag 變更 {n_sr}")
    print(f"[OK] experiment: {exp_path}")


if __name__ == "__main__":
    main()
