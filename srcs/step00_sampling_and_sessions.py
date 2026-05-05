#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step00：抽樣與 session 分配（網站之前置必做）。

目標：
- 從既有「已生成 structured + RAG」的文章範圍（預設 news_id 0001-0104）抽取 30 篇
- 複製出 raw / structured / rag 三份資料到獨立資料庫資料夾，便於後續平台讀取與追溯
- 依規格產出 10 個 session（每 session 12 篇，連續切片，循環取用）
- 為本步驟寫入 intermediate 與 experiment run record（檔名皆帶 step00）

Usage（專案根目錄）：
    python3 srcs/step00_sampling_and_sessions.py
    python3 srcs/step00_sampling_and_sessions.py --seed 20260504 --limit-max-id 104
    python3 srcs/step00_sampling_and_sessions.py --fixed-ids 3 47 8 ... 132
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class SourceLayout:
    raw_dir: Path
    structured_dir: Path
    rag_summary_dir: Path


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git_head() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT)
        ).decode("utf-8", errors="replace")
        return out.strip() or None
    except Exception:
        return None


def _news_id_from_filename(name: str) -> str | None:
    # bench02_{seq}_{news_id}_structured.json / bench02_{seq}_{news_id}_rag.md
    parts = name.split("_")
    if len(parts) < 3:
        return None
    nid = parts[2]
    if len(nid) == 4 and nid.isdigit():
        return nid
    return None


def _discover_available_ids(layout: SourceLayout) -> set[str]:
    if not layout.structured_dir.is_dir():
        raise FileNotFoundError(f"structured_dir 不存在：{layout.structured_dir}")
    if not layout.rag_summary_dir.is_dir():
        raise FileNotFoundError(f"rag_summary_dir 不存在：{layout.rag_summary_dir}")

    struct_ids: set[str] = set()
    for p in layout.structured_dir.glob("bench02_*_*_structured.json"):
        nid = _news_id_from_filename(p.name)
        if nid:
            struct_ids.add(nid)

    rag_ids: set[str] = set()
    for p in layout.rag_summary_dir.glob("bench02_*_*_rag.md"):
        nid = _news_id_from_filename(p.name)
        if nid:
            rag_ids.add(nid)

    return struct_ids & rag_ids


def _find_unique_by_suffix(dir_path: Path, *, suffix: str) -> Path:
    matches = sorted(dir_path.glob(suffix))
    if len(matches) != 1:
        raise RuntimeError(
            f"預期 1 個檔案但找到 {len(matches)} 個：dir={dir_path} suffix={suffix} matches={[m.name for m in matches][:5]}"
        )
    return matches[0]


def _find_raw_by_news_id(raw_dir: Path, news_id: str) -> Path:
    # raw filename is like "0001_....txt"
    matches = sorted(raw_dir.glob(f"{news_id}_*.txt"))
    if len(matches) != 1:
        raise RuntimeError(
            f"預期 1 個 raw 檔但找到 {len(matches)} 個：news_id={news_id} matches={[m.name for m in matches][:5]}"
        )
    return matches[0]


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _copy_file(src: Path, dst: Path) -> None:
    _ensure_dir(dst.parent)
    shutil.copy2(src, dst)


def _build_sessions(sequence: list[str], *, n_sessions: int, per_session: int) -> dict[str, list[str]]:
    if not sequence:
        raise ValueError("sequence 不可為空")
    n = len(sequence)
    out: dict[str, list[str]] = {}
    for s in range(1, n_sessions + 1):
        start = ((s - 1) * per_session) % n
        picked = [sequence[(start + i) % n] for i in range(per_session)]
        out[f"S{s:03d}"] = picked
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Step00：抽樣與 session 分配")
    parser.add_argument("--seed", type=int, default=20260504, help="抽樣 seed（預設 20260504）")
    parser.add_argument("--sample-size", type=int, default=30, help="抽樣篇數（預設 30）")
    parser.add_argument("--n-sessions", type=int, default=10, help="session 數（預設 10）")
    parser.add_argument("--per-session", type=int, default=12, help="每 session 篇數（預設 12）")
    parser.add_argument("--limit-max-id", type=int, default=104, help="僅使用 news_id <= N（預設 104）")
    parser.add_argument(
        "--fixed-ids",
        nargs="+",
        type=int,
        default=None,
        help="固定 news_id 列表（十進位，依此順序寫入 sequence；與隨機抽樣互斥）",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="deepseek-v3",
        help="來源模型資料夾（預設 deepseek-v3）",
    )
    args = parser.parse_args()

    # ── sources ──
    raw_dir = PROJECT_ROOT / "data" / "news_dataset" / "raw"
    bench02_root = PROJECT_ROOT / "intermediate" / "rag_model_compare_bench02"
    model_dir = bench02_root / args.model
    layout = SourceLayout(
        raw_dir=raw_dir,
        structured_dir=model_dir / "structured",
        rag_summary_dir=model_dir / "summary",
    )

    if not raw_dir.is_dir():
        raise FileNotFoundError(f"raw_dir 不存在：{raw_dir}")

    sampling_mode = "random_sample"
    sequence: list[str]
    candidates: list[str]
    limit_max_id_report: int

    if args.fixed_ids is not None:
        sampling_mode = "fixed_order"
        if len(set(args.fixed_ids)) != len(args.fixed_ids):
            raise ValueError("fixed-ids 含重複")
        sequence = [f"{i:04d}" for i in args.fixed_ids]
        limit_max_id_report = max(args.fixed_ids)
        candidates = sequence[:]
        available_ids = _discover_available_ids(layout)
        for nid in sequence:
            if nid not in available_ids:
                raise RuntimeError(
                    f"fixed id {nid} 在 {args.model} 缺少 structured 或 rag："
                    f"{layout.structured_dir} / {layout.rag_summary_dir}"
                )
    else:
        available_ids = _discover_available_ids(layout)
        max_id = int(args.limit_max_id)
        candidates = sorted([nid for nid in available_ids if int(nid) <= max_id])
        limit_max_id_report = max_id

        if len(candidates) < args.sample_size:
            raise RuntimeError(
                f"可用候選不足：candidates={len(candidates)} sample_size={args.sample_size}（limit_max_id={args.limit_max_id}）"
            )

        rng = random.Random(args.seed)
        sampled = sorted(rng.sample(candidates, k=args.sample_size))

        # sequence：固定可追溯（同 seed），但不等於排序（避免永遠低 id 在前）
        sequence = sampled[:]
        rng.shuffle(sequence)

    sessions = _build_sessions(
        sequence,
        n_sessions=args.n_sessions,
        per_session=args.per_session,
    )

    # ── outputs ──
    step_dir = PROJECT_ROOT / "intermediate" / "step00_sampling"
    db_root = step_dir / f"step00_db_{args.model.replace('/', '_')}"
    articles_root = db_root / "articles"
    _ensure_dir(articles_root)
    # 完整重建：刪除舊 articles 子目錄，避免殘留已剔除的 news_id
    for child in articles_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)

    started = datetime.now(timezone.utc).isoformat()
    items: list[dict[str, Any]] = []

    for nid in sequence:
        raw_src = _find_raw_by_news_id(layout.raw_dir, nid)
        struct_src = _find_unique_by_suffix(layout.structured_dir, suffix=f"*_{nid}_structured.json")
        rag_src = _find_unique_by_suffix(layout.rag_summary_dir, suffix=f"*_{nid}_rag.md")

        article_dir = articles_root / nid
        # 資料庫內僅保留原文 + RAG 摘要（.txt）；structured 留在 bench02 路徑供追溯
        original_dst = article_dir / "original.txt"
        rag_dst = article_dir / "summary_rag.txt"

        _copy_file(raw_src, original_dst)
        _copy_file(rag_src, rag_dst)

        items.append(
            {
                "news_id": nid,
                "sources": {
                    "raw": str(raw_src.relative_to(PROJECT_ROOT)),
                    "structured": str(struct_src.relative_to(PROJECT_ROOT)),
                    "rag": str(rag_src.relative_to(PROJECT_ROOT)),
                },
                "copied_to": {
                    "original": str(original_dst.relative_to(PROJECT_ROOT)),
                    "summary_rag": str(rag_dst.relative_to(PROJECT_ROOT)),
                },
            }
        )

    finished = datetime.now(timezone.utc).isoformat()

    sampled_articles_path = step_dir / "step00_sampled_articles_30.json"
    sample_size_report = len(sequence)
    sampled_payload: dict[str, Any] = {
        "step": "step00",
        "kind": "sampling",
        "model": args.model,
        "sampling_mode": sampling_mode,
        "limit_max_id": limit_max_id_report,
        "sample_size": sample_size_report,
        "candidates_count": len(candidates),
        "sequence": sequence,
        "items": items,
        "db_root": str(db_root.relative_to(PROJECT_ROOT)),
        "started_at_utc": started,
        "finished_at_utc": finished,
    }
    if sampling_mode == "fixed_order":
        sampled_payload["fixed_ids"] = args.fixed_ids
        sampled_payload["seed"] = None
    else:
        sampled_payload["seed"] = args.seed

    sampled_articles_path.write_text(
        json.dumps(sampled_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    sessions_path = step_dir / "step00_sessions_10x12.json"
    sessions_path.write_text(
        json.dumps(
            {
                "step": "step00",
                "kind": "sessions",
                "n_sessions": args.n_sessions,
                "per_session": args.per_session,
                "sampling_mode": sampling_mode,
                "sequence": sequence,
                "sessions": sessions,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    exp_dir = PROJECT_ROOT / "experiment"
    _ensure_dir(exp_dir)
    ts = _utc_ts()
    exp_path = exp_dir / f"step00_sampling_run_{ts}.json"
    exp_payload: dict[str, Any] = {
        "step": "step00",
        "script": "srcs/step00_sampling_and_sessions.py",
        "git_head": _git_head(),
        "model": args.model,
        "sampling_mode": sampling_mode,
        "limit_max_id": limit_max_id_report,
        "sample_size": sample_size_report,
        "n_sessions": args.n_sessions,
        "per_session": args.per_session,
        "sources": {
            "raw_dir": str(layout.raw_dir.relative_to(PROJECT_ROOT)),
            "bench02_structured_dir": str(layout.structured_dir.relative_to(PROJECT_ROOT)),
            "bench02_rag_summary_dir": str(layout.rag_summary_dir.relative_to(PROJECT_ROOT)),
        },
        "outputs": {
            "db_root": str(db_root.relative_to(PROJECT_ROOT)),
            "sampled_articles": str(sampled_articles_path.relative_to(PROJECT_ROOT)),
            "sessions": str(sessions_path.relative_to(PROJECT_ROOT)),
        },
        "started_at_utc": started,
        "finished_at_utc": finished,
    }
    if sampling_mode == "fixed_order":
        exp_payload["fixed_ids"] = args.fixed_ids
        exp_payload["seed"] = None
    else:
        exp_payload["seed"] = args.seed
        exp_payload["limit_max_id_random_pool"] = args.limit_max_id

    exp_path.write_text(
        json.dumps(exp_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"[OK] db_root: {db_root}")
    print(f"[OK] sampled: {sampled_articles_path}")
    print(f"[OK] sessions: {sessions_path}")
    print(f"[OK] experiment: {exp_path}")


if __name__ == "__main__":
    main()

