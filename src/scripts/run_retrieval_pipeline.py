"""
端到端 RAG 檢索管線驗證腳本。

對 110 篇 structured 新聞，以指定查詢模式組合
各執行完整的「構建查詢 → 向量化 → 路由檢索 Top-10」流程，
輸出 CSV 供人工抽檢與模式比較。

Usage:
    PYTHONUNBUFFERED=1 python src/scripts/run_retrieval_pipeline.py --preset all
    PYTHONUNBUFFERED=1 python src/scripts/run_retrieval_pipeline.py --preset 5w1h_vs_rights
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.paths import NEWS_RAW_DIR, NEWS_STRUCTURED_DIR
from retrieval.query import (
    QueryMode,
    build_query_text,
    encode_query,
    load_embedding_model,
)
from retrieval.retrieve import RetrievalOutput, retrieve_laws

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
TOP_K = 10

BODY_RE = re.compile(r"【內文】\s*\n(.+)", re.DOTALL)


def _log(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class _NewsRecord:
    """從 structured JSON + raw TXT 讀取的單篇新聞資料。"""

    news_id: str
    title: str
    five_w1h: dict[str, str]
    themes: list[str]
    body: str
    rights_violated: list[str]


def _extract_rights_violated(data: dict) -> list[str]:
    """從 structured JSON 的 events 中彙總所有 rights_violated。"""
    items: list[str] = []
    for ev in data.get("events", []):
        items.extend(ev.get("worker_situation", {}).get("rights_violated", []))
    return items


def _load_news(structured_path: Path) -> _NewsRecord | None:
    """載入單篇新聞的 structured + raw 資料。"""
    with open(structured_path, encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    news_id = meta.get("identifier", structured_path.stem[:4])
    title = meta.get("title", "")
    five_w1h = data.get("5W1H", {})
    themes = data.get("themes", [])
    rights_violated = _extract_rights_violated(data)

    raw_path = NEWS_RAW_DIR / (structured_path.stem + ".txt")
    body = ""
    if raw_path.exists():
        raw_text = raw_path.read_text(encoding="utf-8")
        m = BODY_RE.search(raw_text)
        if m:
            body = m.group(1).strip()

    return _NewsRecord(
        news_id=news_id,
        title=title,
        five_w1h=five_w1h,
        themes=themes,
        body=body,
        rights_violated=rights_violated,
    )


@dataclass
class _ModeResult:
    """單篇新聞在某查詢模式下的檢索結果。"""

    mode: str
    output: RetrievalOutput
    encode_ms: float
    retrieve_ms: float
    error: str = ""


def _run_one_mode(
    news: _NewsRecord,
    mode: QueryMode,
    model,
) -> _ModeResult:
    """對單篇新聞執行單一模式的完整檢索。"""
    try:
        query_text = build_query_text(
            news.five_w1h, news.body, mode=mode,
            rights_violated=news.rights_violated,
        )

        t0 = time.perf_counter()
        vec = encode_query(query_text, model=model)
        encode_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        output = retrieve_laws(vec, news.themes, top_k=TOP_K)
        retrieve_ms = (time.perf_counter() - t1) * 1000

        return _ModeResult(
            mode=mode.value,
            output=output,
            encode_ms=encode_ms,
            retrieve_ms=retrieve_ms,
        )
    except Exception as exc:
        return _ModeResult(
            mode=mode.value,
            output=RetrievalOutput(top_k=TOP_K),
            encode_ms=0,
            retrieve_ms=0,
            error=str(exc),
        )


DETAIL_FIELDS = [
    "news_id", "title", "themes", "query_mode", "rank",
    "law_name", "article_number", "similarity", "distance",
    "routed_theme", "article_text",
]

def _build_compare_fields(labels: list[str]) -> list[str]:
    """根據模式標籤動態產生 comparison CSV 欄位。"""
    fields = ["news_id", "title", "themes"]
    for lb in labels:
        fields.append(f"avg_sim_{lb}")
    for lb in labels:
        fields.extend([f"top1_law_{lb}", f"top1_sim_{lb}"])
    base = labels[0]
    for lb in labels[1:]:
        fields.append(f"diff_{lb}_vs_{base}")
    return fields


def _write_csvs(
    detail_rows: list[dict],
    compare_rows: list[dict],
    compare_fields: list[str],
    suffix: str = "",
) -> tuple[Path, Path]:
    """寫出兩份 CSV，suffix 加在檔名結尾。"""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    tag = f"_{suffix}" if suffix else ""
    detail_path = OUTPUTS_DIR / f"retrieval_results{tag}.csv"
    with open(detail_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        w.writeheader()
        w.writerows(detail_rows)

    compare_path = OUTPUTS_DIR / f"retrieval_comparison{tag}.csv"
    with open(compare_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=compare_fields)
        w.writeheader()
        w.writerows(compare_rows)

    return detail_path, compare_path


def _avg_sim(results: list) -> float:
    """計算結果列表的平均相似度。"""
    if not results:
        return 0.0
    return sum(r.similarity for r in results) / len(results)


def _print_mode_stats(label: str, mode_results: list[_ModeResult]) -> None:
    """輸出單一模式的統計。"""
    n = len(mode_results)
    ok = sum(1 for r in mode_results if not r.error and r.output.results)
    err = sum(1 for r in mode_results if r.error)
    _log(f"  {label}: 成功={ok}/{n}  錯誤={err}")

    sims = [r.similarity for mr in mode_results for r in mr.output.results]
    if sims:
        _log(f"    相似度  平均={statistics.mean(sims):.4f}  "
             f"中位={statistics.median(sims):.4f}  "
             f"最高={max(sims):.4f}  最低={min(sims):.4f}")

    top1 = [mr.output.results[0].similarity for mr in mode_results
            if mr.output.results]
    if top1:
        _log(f"    Top-1   平均={statistics.mean(top1):.4f}  "
             f"中位={statistics.median(top1):.4f}")


def _print_summary(
    all_modes: dict[str, list[_ModeResult]],
    theme_counter: Counter,
    total_time: float,
) -> None:
    """輸出終端統計摘要。"""
    _log("\n" + "=" * 60)
    _log("  RAG Pipeline Validation — 統計摘要")
    _log("=" * 60)

    n = len(next(iter(all_modes.values())))
    _log(f"\n總新聞數: {n}")

    for label, results in all_modes.items():
        _print_mode_stats(label, results)

    _log(f"\nTheme 路由分佈（被路由到的次數）:")
    for theme, cnt in theme_counter.most_common():
        _log(f"  {theme}: {cnt}")

    skipped_all: Counter = Counter()
    first_mode = next(iter(all_modes.values()))
    for mr in first_mode:
        for s in mr.output.skipped_themes:
            skipped_all[s] += 1
    if skipped_all:
        _log(f"\n未識別 theme（跳過）:")
        for t, c in skipped_all.most_common():
            _log(f"  {t}: {c}")

    all_results = [mr for results in all_modes.values() for mr in results]
    valid = [mr for mr in all_results if not mr.error]
    avg_encode = statistics.mean([mr.encode_ms for mr in valid]) if valid else 0
    avg_retrieve = statistics.mean([mr.retrieve_ms for mr in valid]) if valid else 0

    _log(f"\n平均延遲:  encode={avg_encode:.1f}ms  retrieve={avg_retrieve:.1f}ms")
    _log(f"總耗時: {total_time:.1f}s")
    _log("=" * 60)


ALL_MODE_LABELS = {
    QueryMode.FIVE_W1H_ONLY: "5w1h",
    QueryMode.FIVE_W1H_WITH_BODY: "body",
    QueryMode.FIVE_W1H_WITH_RIGHTS: "rights",
}

PRESETS: dict[str, tuple[list[QueryMode], str]] = {
    "all": (
        [QueryMode.FIVE_W1H_ONLY, QueryMode.FIVE_W1H_WITH_BODY,
         QueryMode.FIVE_W1H_WITH_RIGHTS],
        "all_modes",
    ),
    "5w1h_vs_rights": (
        [QueryMode.FIVE_W1H_ONLY, QueryMode.FIVE_W1H_WITH_RIGHTS],
        "5w1h_vs_rights",
    ),
}


def _top1_fields(label: str, results: list) -> dict:
    """產生單一模式的 top1 comparison 欄位。"""
    top1 = results[0] if results else None
    return {
        f"top1_law_{label}": (f"《{top1.law_name}》{top1.article_number}"
                              if top1 else ""),
        f"top1_sim_{label}": f"{top1.similarity:.4f}" if top1 else "",
    }


def _run_preset(modes: list[QueryMode], suffix: str) -> None:
    """以指定模式組合執行完整管線並輸出 CSV。"""
    labels = [ALL_MODE_LABELS[m] for m in modes]
    compare_fields = _build_compare_fields(labels)

    _log(f"\n{'─' * 60}")
    _log(f"  Preset: {suffix}  模式: {', '.join(labels)}")
    _log(f"{'─' * 60}")

    _log("載入 embedding 模型…")
    t_start = time.perf_counter()
    model = load_embedding_model()
    _log(f"模型載入完成（{(time.perf_counter() - t_start):.1f}s）")

    structured_files = sorted(NEWS_STRUCTURED_DIR.glob("*.json"))
    _log(f"找到 {len(structured_files)} 篇 structured 新聞")

    detail_rows: list[dict] = []
    compare_rows: list[dict] = []
    all_modes_data: dict[str, list[_ModeResult]] = {lb: [] for lb in labels}
    theme_counter: Counter = Counter()

    t_pipeline = time.perf_counter()

    for idx, sf in enumerate(structured_files):
        news = _load_news(sf)
        if news is None:
            _log(f"  [{idx+1}/{len(structured_files)}] SKIP (載入失敗): {sf.name}")
            continue

        _log(f"  [{idx+1}/{len(structured_files)}] {news.news_id} — {news.title[:40]}…")

        mode_results: dict[str, _ModeResult] = {}
        for mode in modes:
            label = ALL_MODE_LABELS[mode]
            res = _run_one_mode(news, mode, model)
            mode_results[label] = res
            all_modes_data[label].append(res)

        for routed in mode_results[labels[0]].output.routed_themes:
            theme_counter[routed] += 1

        themes_str = "; ".join(news.themes)

        for label, mr in mode_results.items():
            if mr.error:
                detail_rows.append({
                    "news_id": news.news_id,
                    "title": news.title,
                    "themes": themes_str,
                    "query_mode": mr.mode,
                    "rank": 0,
                    "law_name": f"ERROR: {mr.error}",
                    "article_number": "",
                    "similarity": "",
                    "distance": "",
                    "routed_theme": "",
                    "article_text": "",
                })
                continue
            for rank, r in enumerate(mr.output.results, 1):
                detail_rows.append({
                    "news_id": news.news_id,
                    "title": news.title,
                    "themes": themes_str,
                    "query_mode": mr.mode,
                    "rank": rank,
                    "law_name": r.law_name,
                    "article_number": r.article_number,
                    "similarity": f"{r.similarity:.4f}",
                    "distance": f"{r.distance:.4f}",
                    "routed_theme": r.theme,
                    "article_text": r.text,
                })

        avg = {lb: _avg_sim(mr.output.results) for lb, mr in mode_results.items()}
        base_label = labels[0]

        row: dict = {
            "news_id": news.news_id,
            "title": news.title,
            "themes": themes_str,
        }
        for lb in labels:
            row[f"avg_sim_{lb}"] = f"{avg[lb]:.4f}"
        for lb, mr in mode_results.items():
            row.update(_top1_fields(lb, mr.output.results))
        for lb in labels[1:]:
            row[f"diff_{lb}_vs_{base_label}"] = f"{avg[lb] - avg[base_label]:.4f}"

        compare_rows.append(row)

    total_time = time.perf_counter() - t_pipeline

    detail_path, compare_path = _write_csvs(
        detail_rows, compare_rows, compare_fields, suffix,
    )
    _log(f"\n全量明細 → {detail_path}")
    _log(f"對比摘要 → {compare_path}")

    _print_summary(all_modes_data, theme_counter, total_time)


def main() -> None:
    """主函式。"""
    parser = argparse.ArgumentParser(description="RAG 檢索管線驗證")
    parser.add_argument(
        "--preset", choices=list(PRESETS), default="all",
        help="模式組合預設（預設 all）",
    )
    args = parser.parse_args()

    modes, suffix = PRESETS[args.preset]
    _run_preset(modes, suffix)


if __name__ == "__main__":
    main()
