#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bench02：多模型 RAG 摘要對照資料產生。

對每篇 raw（依序號）：依序對**所有**指定模型各跑一遍（結構化 → RAG → 摘要），再換下一篇。
API Key / Base URL 僅來自 .env。

Usage（專案根目錄）:
    python3 src/scripts/bench_02_rag_multimodel.py
    python3 src/scripts/bench_02_rag_multimodel.py --limit 10 --models qwen-max deepseek-v3
    python3 src/scripts/bench_02_rag_multimodel.py --overwrite
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from config.paths import NEWS_RAW_DIR
from scripts.extract_schema import extract_structured_from_raw
from scripts.summarize_news import summarize_single

# 預設模型（不含 kimi）；可 --models 覆寫或擴充
DEFAULT_MODELS: tuple[str, ...] = (
    "qwen-max",
    "glm-5",
    "deepseek-v3",
)

BENCH02_ROOT = PROJECT_ROOT / "intermediate" / "rag_model_compare_bench02"
EXPERIMENT_DIR = PROJECT_ROOT / "experiment"


def _model_dir_name(model: str) -> str:
    return model.replace("/", "_").replace("\\", "_")


def _news_id_from_raw_path(raw_path: Path) -> str:
    m = re.match(r"^(\d{1,4})_", raw_path.name)
    if m:
        return m.group(1).zfill(4)
    return "0000"


def _process_one(
    *,
    raw_path: Path,
    seq: int,
    model: str,
    structured_dir: Path,
    summary_dir: Path,
    top_k: int,
    max_retries: int,
    overwrite: bool,
) -> dict[str, Any]:
    nid = _news_id_from_raw_path(raw_path)
    base = f"bench02_{seq:02d}_{nid}"
    struct_path = structured_dir / f"{base}_structured.json"
    summ_path = summary_dir / f"{base}_rag.md"

    rec: dict[str, Any] = {
        "seq": seq,
        "news_id": nid,
        "raw": str(raw_path.relative_to(PROJECT_ROOT)),
        "model": model,
        "structured_path": str(struct_path.relative_to(PROJECT_ROOT)),
        "summary_path": str(summ_path.relative_to(PROJECT_ROOT)),
        "ok": False,
        "error": None,
        "skipped": False,
    }

    if (
        not overwrite
        and struct_path.is_file()
        and summ_path.is_file()
    ):
        rec["skipped"] = True
        rec["ok"] = True
        return rec

    try:
        structured = extract_structured_from_raw(
            raw_path, max_retries=max_retries, model=model
        )
        struct_path.write_text(
            json.dumps(structured, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        summary = summarize_single(
            raw_path,
            structured,
            use_rag=True,
            top_k=top_k,
            max_retries=max_retries,
            model=model,
        )
        header = (
            f"<!-- bench02 | model={model} | rag | source={raw_path.name} | seq={seq} -->\n\n"
        )
        summ_path.write_text(header + summary + "\n", encoding="utf-8")
        rec["ok"] = True
    except Exception as e:
        rec["error"] = str(e)

    return rec


def main() -> None:
    parser = argparse.ArgumentParser(description="bench02：多模型 RAG 摘要批次")
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="raw 排序後前 N 篇；每篇內依序跑完所有模型（預設 5）",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=list(DEFAULT_MODELS),
        help="模型名列表（預設 qwen-max / glm-5 / deepseek-v3）",
    )
    parser.add_argument("--top-k", type=int, default=10, help="RAG Top-k（預設 10）")
    parser.add_argument(
        "--max-retries", type=int, default=3, help="每步 LLM 重試次數（預設 3）"
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="已存在輸出仍重新生成",
    )
    args = parser.parse_args()

    if not args.models:
        print("錯誤：至少指定一個 --models", file=sys.stderr)
        sys.exit(1)

    raw_dir = NEWS_RAW_DIR
    if not raw_dir.is_dir():
        print(f"錯誤：{raw_dir} 不存在", file=sys.stderr)
        sys.exit(1)

    all_txt = sorted(raw_dir.glob("*.txt"))
    if not all_txt:
        print(f"錯誤：{raw_dir} 下無 .txt", file=sys.stderr)
        sys.exit(1)

    batch = all_txt[: args.limit]
    started = datetime.now(timezone.utc).isoformat()

    BENCH02_ROOT.mkdir(parents=True, exist_ok=True)
    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)

    run_payload: dict[str, Any] = {
        "step": "bench02",
        "script": "src/scripts/bench_02_rag_multimodel.py",
        "schema_prompt": "src/prompts/schema_extraction_prompt.py",
        "summary_prompt": "src/prompts/summary_prompt.py",
        "rag": "src/retrieval/retrieve.py（Chroma 知識庫與主專案相同）",
        "started_at_utc": started,
        "limit": args.limit,
        "top_k": args.top_k,
        "execution_order": "by_article_then_models",
        "models": [],
    }

    any_ok = False

    model_dirs: dict[str, tuple[Path, Path, Path]] = {}
    for model in args.models:
        mdir = BENCH02_ROOT / _model_dir_name(model)
        structured_dir = mdir / "structured"
        summary_dir = mdir / "summary"
        structured_dir.mkdir(parents=True, exist_ok=True)
        summary_dir.mkdir(parents=True, exist_ok=True)
        model_dirs[model] = (mdir, structured_dir, summary_dir)

    model_records: dict[str, list[dict[str, Any]]] = {
        m: [] for m in args.models
    }

    for seq, raw_path in enumerate(batch, start=1):
        for model in args.models:
            _, structured_dir, summary_dir = model_dirs[model]
            print(
                f"[bench02] seq {seq}/{len(batch)} | {model} | {raw_path.name}",
                file=sys.stderr,
                flush=True,
            )
            rec = _process_one(
                raw_path=raw_path,
                seq=seq,
                model=model,
                structured_dir=structured_dir,
                summary_dir=summary_dir,
                top_k=args.top_k,
                max_retries=args.max_retries,
                overwrite=args.overwrite,
            )
            model_records[model].append(rec)
            if rec.get("ok"):
                any_ok = True

    for model in args.models:
        mdir, _, _ = model_dirs[model]
        records = model_records[model]
        manifest_path = mdir / "bench02_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "step": "bench02",
                    "model": model,
                    "execution_order": "by_article_then_models",
                    "items": records,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        run_payload["models"].append(
            {
                "model": model,
                "output_dir": str(mdir.relative_to(PROJECT_ROOT)),
                "manifest": str(manifest_path.relative_to(PROJECT_ROOT)),
                "records": records,
            }
        )

    finished = datetime.now(timezone.utc).isoformat()
    run_payload["finished_at_utc"] = finished

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    exp_path = EXPERIMENT_DIR / f"bench02_run_{ts}.json"
    exp_path.write_text(
        json.dumps(run_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"experiment: {exp_path}", file=sys.stderr)
    print(f"outputs under: {BENCH02_ROOT}", file=sys.stderr)

    if not any_ok:
        print("錯誤：沒有任何成功項目。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
