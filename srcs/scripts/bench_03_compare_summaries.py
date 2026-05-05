#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bench03：多模型 RAG 摘要 vs bench01 偽參考 — BLEU / ROUGE 整體對比。

對每個模型，在與 benchmark 對齊的若干篇上計算：
  - BLEU-1、BLEU-4（corpus-level，jieba 詞級 token）
  - ROUGE-1、ROUGE-2、ROUGE-L（macro：逐篇 F1 再平均，jieba 分詞 + 自訂 tokenizer）

結果寫入 intermediate/outputs/。

Usage（專案根目錄）:
    python3 srcs/scripts/bench_03_compare_summaries.py
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import jieba
from dotenv import load_dotenv
from nltk.translate.bleu_score import SmoothingFunction, corpus_bleu
from rouge_score import rouge_scorer
from rouge_score.tokenizers import Tokenizer

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SRC_ROOT = PROJECT_ROOT / "srcs"
sys.path.insert(0, str(SRC_ROOT))

from config.paths import OUTPUTS_DIR

DEFAULT_MODELS: tuple[str, ...] = ("qwen-max", "glm-5", "deepseek-v3")

BENCH01_STEM_RE = re.compile(
    r"^bench01_(\d+)_(\d{4})_.*_reference\.md$"
)
BENCH02_STEM_RE = re.compile(r"^bench02_(\d+)_(\d{4})_rag\.md$")

_smooth = SmoothingFunction().method1


class JiebaTokenizer(Tokenizer):
    """供 RougeScorer 使用：略過套件預設的英數 tokenizer，避免中文被清空。"""

    def tokenize(self, text: str) -> list[str]:
        s = re.sub(r"\s+", "", (text or "").strip())
        if not s:
            return []
        return [t for t in jieba.lcut(s) if t.strip()]


def _model_dir_name(model: str) -> str:
    return model.replace("/", "_").replace("\\", "_")


def _strip_md_header(text: str) -> str:
    lines = text.split("\n")
    if lines and lines[0].strip().startswith("<!--"):
        text = "\n".join(lines[1:]).lstrip("\n")
    return text.strip()


def _normalize_cjk_text(s: str) -> str:
    """去掉換行與多餘空白，供 jieba 連續分詞。"""
    return re.sub(r"\s+", "", (s or "").strip())


def _jieba_tokens(s: str) -> list[str]:
    """jieba 詞級 token，供 BLEU corpus。"""
    body = _normalize_cjk_text(s)
    if not body:
        return []
    toks = [t for t in jieba.lcut(body) if t.strip()]
    return toks


def _load_benchmark_map(bench01_dir: Path) -> dict[tuple[int, str], str]:
    out: dict[tuple[int, str], str] = {}
    for p in sorted(bench01_dir.glob("bench01_*_reference.md")):
        m = BENCH01_STEM_RE.match(p.name)
        if not m:
            continue
        seq, nid = int(m.group(1)), m.group(2)
        body = _strip_md_header(p.read_text(encoding="utf-8"))
        if body:
            out[(seq, nid)] = body
    return out


def _load_summaries_for_model(
    bench02_root: Path,
    model: str,
) -> dict[tuple[int, str], str]:
    summ_dir = bench02_root / _model_dir_name(model) / "summary"
    out: dict[tuple[int, str], str] = {}
    if not summ_dir.is_dir():
        return out
    for p in summ_dir.glob("bench02_*_rag.md"):
        m = BENCH02_STEM_RE.match(p.name)
        if not m:
            continue
        seq, nid = int(m.group(1)), m.group(2)
        body = _strip_md_header(p.read_text(encoding="utf-8"))
        if body:
            out[(seq, nid)] = body
    return out


def _corpus_bleu(refs: list[str], hyps: list[str], weights: tuple[float, ...]) -> float:
    ref_toks = [[_jieba_tokens(r)] for r in refs]
    hyp_toks = [_jieba_tokens(h) for h in hyps]
    # 空序列會讓 BLEU 不穩定，改為單一占位
    ref_toks = [r if r[0] else [["∅"]] for r in ref_toks]
    hyp_toks = [h if h else ["∅"] for h in hyp_toks]
    return float(
        corpus_bleu(ref_toks, hyp_toks, weights=weights, smoothing_function=_smooth)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="bench03：摘要 vs benchmark 指標對比")
    parser.add_argument(
        "--bench01-dir",
        type=Path,
        default=PROJECT_ROOT / "intermediate" / "benchmark_bench01",
        help="bench01 參考摘要目錄",
    )
    parser.add_argument(
        "--bench02-root",
        type=Path,
        default=PROJECT_ROOT / "intermediate" / "rag_model_compare_bench02",
        help="bench02 多模型輸出根目錄",
    )
    parser.add_argument(
        "--models",
        nargs="*",
        default=list(DEFAULT_MODELS),
        help="模型名（與 bench02 子目錄一致）",
    )
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        default=PROJECT_ROOT / "experiment",
        help="實驗紀錄目錄",
    )
    args = parser.parse_args()

    if not args.models:
        print("錯誤：至少指定一個 --models", file=sys.stderr)
        sys.exit(1)

    jieba.setLogLevel(logging.ERROR)  # 降低首次載入詞典時的 log 噪音

    bench_map = _load_benchmark_map(args.bench01_dir)
    if not bench_map:
        print(f"錯誤：{args.bench01_dir} 無可用 bench01 參考", file=sys.stderr)
        sys.exit(1)

    scorer = rouge_scorer.RougeScorer(
        ["rouge1", "rouge2", "rougeL"],
        use_stemmer=False,
        tokenizer=JiebaTokenizer(),
    )

    started = datetime.now(timezone.utc).isoformat()
    model_metrics: dict[str, dict[str, float]] = {}
    model_per_doc: dict[str, list[dict[str, Any]]] = {}
    all_keys_used: set[tuple[int, str]] = set()

    for model in args.models:
        summ_map = _load_summaries_for_model(args.bench02_root, model)
        keys = sorted(set(bench_map.keys()) & set(summ_map.keys()))
        if not keys:
            print(f"[WARN] {model}：與 benchmark 無交集，跳過", file=sys.stderr)
            model_metrics[model] = {
                "bleu1": 0.0,
                "bleu4": 0.0,
                "rouge1_f": 0.0,
                "rouge2_f": 0.0,
                "rougeL_f": 0.0,
                "n_pairs": 0,
            }
            model_per_doc[model] = []
            continue

        all_keys_used.update(keys)
        refs = [bench_map[k] for k in keys]
        hyps = [summ_map[k] for k in keys]

        bleu1 = _corpus_bleu(refs, hyps, (1.0, 0.0, 0.0, 0.0))
        bleu4 = _corpus_bleu(refs, hyps, (0.25, 0.25, 0.25, 0.25))

        r1_sum = r2_sum = rl_sum = 0.0
        per_doc: list[dict[str, Any]] = []
        for k in keys:
            rt = _normalize_cjk_text(bench_map[k])
            ht = _normalize_cjk_text(summ_map[k])
            rs = scorer.score(rt, ht)
            r1 = rs["rouge1"].fmeasure
            r2 = rs["rouge2"].fmeasure
            rl = rs["rougeL"].fmeasure
            r1_sum += r1
            r2_sum += r2
            rl_sum += rl
            per_doc.append(
                {
                    "seq": k[0],
                    "news_id": k[1],
                    "rouge1_f": round(r1, 6),
                    "rouge2_f": round(r2, 6),
                    "rougeL_f": round(rl, 6),
                }
            )

        n = len(keys)
        model_metrics[model] = {
            "bleu1": round(bleu1, 6),
            "bleu4": round(bleu4, 6),
            "rouge1_f": round(r1_sum / n, 6),
            "rouge2_f": round(r2_sum / n, 6),
            "rougeL_f": round(rl_sum / n, 6),
            "n_pairs": n,
        }
        model_per_doc[model] = per_doc

    finished = datetime.now(timezone.utc).isoformat()

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "step": "bench03",
        "script": "src/scripts/bench_03_compare_summaries.py",
        "started_at_utc": started,
        "finished_at_utc": finished,
        "bench01_dir": str(args.bench01_dir.relative_to(PROJECT_ROOT)),
        "bench02_root": str(args.bench02_root.relative_to(PROJECT_ROOT)),
        "models": list(args.models),
        "matched_keys_union": [list(t) for t in sorted(all_keys_used)],
        "aggregation": {
            "bleu1_bleu4": "corpus-level（jieba 詞級 token），Smoothing method1",
            "rouge": "macro：逐篇 F1 平均（jieba 分詞 + JiebaTokenizer）",
        },
        "metrics_by_model": model_metrics,
        "per_document": model_per_doc,
    }

    out_json = OUTPUTS_DIR / "bench03_compare_metrics.json"
    out_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Markdown 表（便於贴進報告）
    lines = [
        "# bench03：摘要 vs benchmark 指標",
        "",
        f"- 產生時間（UTC）：{finished}",
        f"- 對齊篇數（各模型）：見 `n_pairs`",
        "",
        "| model | n_pairs | BLEU-1 | BLEU-4 | ROUGE-1 F1 | ROUGE-2 F1 | ROUGE-L F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for m in args.models:
        mm = model_metrics.get(m, {})
        lines.append(
            f"| {m} | {mm.get('n_pairs', 0)} | {mm.get('bleu1', 0)} | {mm.get('bleu4', 0)} | "
            f"{mm.get('rouge1_f', 0)} | {mm.get('rouge2_f', 0)} | {mm.get('rougeL_f', 0)} |"
        )
    lines.append("")
    lines.append(f"完整 JSON：`{out_json.relative_to(PROJECT_ROOT)}`")
    out_md = OUTPUTS_DIR / "bench03_compare_table.md"
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    args.experiment_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    exp_path = args.experiment_dir / f"bench03_run_{ts}.json"
    exp_path.write_text(
        json.dumps(
            {
                "step": "bench03",
                "outputs": {
                    "json": str(out_json.relative_to(PROJECT_ROOT)),
                    "markdown": str(out_md.relative_to(PROJECT_ROOT)),
                },
                "metrics_by_model": model_metrics,
                "finished_at_utc": finished,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {out_json}", file=sys.stderr)
    print(f"Wrote {out_md}", file=sys.stderr)
    print(f"Wrote {exp_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
