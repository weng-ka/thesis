"""
端到端 RAG 檢索管線驗證腳本。

對 110 篇 structured 新聞，以兩種查詢模式（5W1H-only / 5W1H+body）
各執行完整的「構建查詢 → 向量化 → 路由檢索 Top-10」流程，
輸出 CSV 供人工抽檢與模式比較。

Usage:
    PYTHONUNBUFFERED=1 python src/scripts/run_retrieval_pipeline.py
"""

from __future__ import annotations

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


def _load_news(structured_path: Path) -> _NewsRecord | None:
    """載入單篇新聞的 structured + raw 資料。"""
    with open(structured_path, encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    news_id = meta.get("identifier", structured_path.stem[:4])
    title = meta.get("title", "")
    five_w1h = data.get("5W1H", {})
    themes = data.get("themes", [])

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
        query_text = build_query_text(news.five_w1h, news.body, mode=mode)

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

COMPARE_FIELDS = [
    "news_id", "title", "themes",
    "avg_sim_5w1h", "avg_sim_body",
    "top1_law_5w1h", "top1_sim_5w1h",
    "top1_law_body", "top1_sim_body",
    "sim_diff",
]


def _write_csvs(
    detail_rows: list[dict],
    compare_rows: list[dict],
) -> tuple[Path, Path]:
    """寫出兩份 CSV。"""
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    detail_path = OUTPUTS_DIR / "retrieval_results.csv"
    with open(detail_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=DETAIL_FIELDS)
        w.writeheader()
        w.writerows(detail_rows)

    compare_path = OUTPUTS_DIR / "retrieval_comparison.csv"
    with open(compare_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COMPARE_FIELDS)
        w.writeheader()
        w.writerows(compare_rows)

    return detail_path, compare_path


def _avg_sim(results: list) -> float:
    """計算結果列表的平均相似度。"""
    if not results:
        return 0.0
    return sum(r.similarity for r in results) / len(results)


def _print_summary(
    all_5w1h: list[_ModeResult],
    all_body: list[_ModeResult],
    theme_counter: Counter,
    total_time: float,
) -> None:
    """輸出終端統計摘要。"""
    _log("\n" + "=" * 60)
    _log("  RAG Pipeline Validation — 統計摘要")
    _log("=" * 60)

    n = len(all_5w1h)
    ok_5w1h = sum(1 for r in all_5w1h if not r.error and r.output.results)
    ok_body = sum(1 for r in all_body if not r.error and r.output.results)
    err_5w1h = sum(1 for r in all_5w1h if r.error)
    err_body = sum(1 for r in all_body if r.error)

    _log(f"\n總新聞數: {n}")
    _log(f"成功檢索（有結果）: 5W1H-only={ok_5w1h}/{n}, 5W1H+body={ok_body}/{n}")
    _log(f"錯誤數: 5W1H-only={err_5w1h}, 5W1H+body={err_body}")

    sims_5w1h = [r.similarity for mr in all_5w1h for r in mr.output.results]
    sims_body = [r.similarity for mr in all_body for r in mr.output.results]

    if sims_5w1h:
        _log(f"\n[5W1H-only] 相似度:")
        _log(f"  平均={statistics.mean(sims_5w1h):.4f}  "
             f"中位={statistics.median(sims_5w1h):.4f}  "
             f"最高={max(sims_5w1h):.4f}  最低={min(sims_5w1h):.4f}")

    if sims_body:
        _log(f"\n[5W1H+body] 相似度:")
        _log(f"  平均={statistics.mean(sims_body):.4f}  "
             f"中位={statistics.median(sims_body):.4f}  "
             f"最高={max(sims_body):.4f}  最低={min(sims_body):.4f}")

    top1_5w1h = [mr.output.results[0].similarity for mr in all_5w1h
                 if mr.output.results]
    top1_body = [mr.output.results[0].similarity for mr in all_body
                 if mr.output.results]
    if top1_5w1h and top1_body:
        _log(f"\nTop-1 相似度對比:")
        _log(f"  5W1H-only  平均={statistics.mean(top1_5w1h):.4f}  "
             f"中位={statistics.median(top1_5w1h):.4f}")
        _log(f"  5W1H+body  平均={statistics.mean(top1_body):.4f}  "
             f"中位={statistics.median(top1_body):.4f}")

    _log(f"\nTheme 路由分佈（被路由到的次數）:")
    for theme, cnt in theme_counter.most_common():
        _log(f"  {theme}: {cnt}")

    skipped_all = Counter()
    for mr in all_5w1h:
        for s in mr.output.skipped_themes:
            skipped_all[s] += 1
    if skipped_all:
        _log(f"\n未識別 theme（跳過）:")
        for t, c in skipped_all.most_common():
            _log(f"  {t}: {c}")

    avg_encode = statistics.mean(
        [mr.encode_ms for mr in all_5w1h + all_body if not mr.error]
    ) if any(not mr.error for mr in all_5w1h + all_body) else 0
    avg_retrieve = statistics.mean(
        [mr.retrieve_ms for mr in all_5w1h + all_body if not mr.error]
    ) if any(not mr.error for mr in all_5w1h + all_body) else 0

    _log(f"\n平均延遲:  encode={avg_encode:.1f}ms  retrieve={avg_retrieve:.1f}ms")
    _log(f"總耗時: {total_time:.1f}s")
    _log("=" * 60)


def main() -> None:
    """主函式。"""
    _log("載入 embedding 模型…")
    t_start = time.perf_counter()
    model = load_embedding_model()
    _log(f"模型載入完成（{(time.perf_counter() - t_start):.1f}s）")

    structured_files = sorted(NEWS_STRUCTURED_DIR.glob("*.json"))
    _log(f"找到 {len(structured_files)} 篇 structured 新聞")

    detail_rows: list[dict] = []
    compare_rows: list[dict] = []
    all_5w1h: list[_ModeResult] = []
    all_body: list[_ModeResult] = []
    theme_counter: Counter = Counter()

    t_pipeline = time.perf_counter()

    for idx, sf in enumerate(structured_files):
        news = _load_news(sf)
        if news is None:
            _log(f"  [{idx+1}/{len(structured_files)}] SKIP (載入失敗): {sf.name}")
            continue

        _log(f"  [{idx+1}/{len(structured_files)}] {news.news_id} — {news.title[:40]}…")

        res_5w1h = _run_one_mode(news, QueryMode.FIVE_W1H_ONLY, model)
        res_body = _run_one_mode(news, QueryMode.FIVE_W1H_WITH_BODY, model)

        all_5w1h.append(res_5w1h)
        all_body.append(res_body)

        for routed in res_5w1h.output.routed_themes:
            theme_counter[routed] += 1
        for routed in res_body.output.routed_themes:
            theme_counter[routed] += 1

        themes_str = "; ".join(news.themes)

        for mr in (res_5w1h, res_body):
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

        avg_5 = _avg_sim(res_5w1h.output.results)
        avg_b = _avg_sim(res_body.output.results)
        top1_5 = res_5w1h.output.results[0] if res_5w1h.output.results else None
        top1_b = res_body.output.results[0] if res_body.output.results else None

        compare_rows.append({
            "news_id": news.news_id,
            "title": news.title,
            "themes": themes_str,
            "avg_sim_5w1h": f"{avg_5:.4f}",
            "avg_sim_body": f"{avg_b:.4f}",
            "top1_law_5w1h": (f"《{top1_5.law_name}》{top1_5.article_number}"
                              if top1_5 else ""),
            "top1_sim_5w1h": f"{top1_5.similarity:.4f}" if top1_5 else "",
            "top1_law_body": (f"《{top1_b.law_name}》{top1_b.article_number}"
                              if top1_b else ""),
            "top1_sim_body": f"{top1_b.similarity:.4f}" if top1_b else "",
            "sim_diff": f"{avg_b - avg_5:.4f}",
        })

    total_time = time.perf_counter() - t_pipeline

    detail_path, compare_path = _write_csvs(detail_rows, compare_rows)
    _log(f"\n全量明細 → {detail_path}")
    _log(f"對比摘要 → {compare_path}")

    _print_summary(all_5w1h, all_body, theme_counter, total_time)


if __name__ == "__main__":
    main()
