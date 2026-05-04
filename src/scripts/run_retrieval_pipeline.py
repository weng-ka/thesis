"""
端到端 RAG 檢索管線腳本。

對所有 structured 新聞執行完整的
「構建查詢（5W1H + rights_violated）→ 向量化 → 路由檢索 Top-10」流程，
輸出 CSV 供人工抽檢。

Usage:
    PYTHONUNBUFFERED=1 python src/scripts/run_retrieval_pipeline.py
"""

from __future__ import annotations

import csv
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.paths import NEWS_STRUCTURED_DIR, OUTPUTS_DIR
from retrieval.query import build_query_text, encode_query, load_embedding_model
from retrieval.retrieve import RetrievalOutput, retrieve_laws

TOP_K = 10

DETAIL_FIELDS = [
    "news_id", "title", "themes", "rank",
    "law_name", "article_number", "similarity", "distance",
    "routed_theme", "article_text",
]


def _log(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class _NewsRecord:
    """從 structured JSON 讀取的單篇新聞資料。"""

    news_id: str
    title: str
    five_w1h: dict[str, str]
    themes: list[str]
    rights_violated: list[str]


def _extract_rights_violated(data: dict) -> list[str]:
    """從 structured JSON 的 events 中彙總所有 rights_violated。"""
    items: list[str] = []
    for ev in data.get("events", []):
        items.extend(ev.get("worker_situation", {}).get("rights_violated", []))
    return items


def _load_news(structured_path: Path) -> _NewsRecord | None:
    """載入單篇新聞的 structured 資料。"""
    with open(structured_path, encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    return _NewsRecord(
        news_id=meta.get("identifier", structured_path.stem[:4]),
        title=meta.get("title", ""),
        five_w1h=data.get("5W1H", {}),
        themes=data.get("themes", []),
        rights_violated=_extract_rights_violated(data),
    )


@dataclass
class _Result:
    """單篇新聞的檢索結果。"""

    output: RetrievalOutput
    encode_ms: float
    retrieve_ms: float
    error: str = ""


def _run_retrieval(news: _NewsRecord, model) -> _Result:
    """對單篇新聞執行完整檢索。"""
    try:
        query_text = build_query_text(news.five_w1h, news.rights_violated)

        t0 = time.perf_counter()
        vec = encode_query(query_text, model=model)
        encode_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        output = retrieve_laws(vec, news.themes, top_k=TOP_K)
        retrieve_ms = (time.perf_counter() - t1) * 1000

        return _Result(output=output, encode_ms=encode_ms, retrieve_ms=retrieve_ms)
    except Exception as exc:
        return _Result(
            output=RetrievalOutput(top_k=TOP_K),
            encode_ms=0, retrieve_ms=0, error=str(exc),
        )


def _print_summary(
    all_results: list[_Result],
    theme_counter: Counter,
    total_time: float,
) -> None:
    """輸出終端統計摘要。"""
    _log("\n" + "=" * 60)
    _log("  RAG Pipeline — 統計摘要")
    _log("=" * 60)

    n = len(all_results)
    ok = sum(1 for r in all_results if not r.error and r.output.results)
    err = sum(1 for r in all_results if r.error)
    _log(f"\n總新聞數: {n}  成功: {ok}  錯誤: {err}")

    sims = [r.similarity for res in all_results for r in res.output.results]
    if sims:
        _log(f"\n相似度:")
        _log(f"  平均={statistics.mean(sims):.4f}  "
             f"中位={statistics.median(sims):.4f}  "
             f"最高={max(sims):.4f}  最低={min(sims):.4f}")

    top1 = [res.output.results[0].similarity for res in all_results
            if res.output.results]
    if top1:
        _log(f"  Top-1  平均={statistics.mean(top1):.4f}  "
             f"中位={statistics.median(top1):.4f}")

    _log(f"\nTheme 路由分佈:")
    for theme, cnt in theme_counter.most_common():
        _log(f"  {theme}: {cnt}")

    skipped: Counter = Counter()
    for res in all_results:
        for s in res.output.skipped_themes:
            skipped[s] += 1
    if skipped:
        _log(f"\n未識別 theme（跳過）:")
        for t, c in skipped.most_common():
            _log(f"  {t}: {c}")

    valid = [r for r in all_results if not r.error]
    avg_enc = statistics.mean([r.encode_ms for r in valid]) if valid else 0
    avg_ret = statistics.mean([r.retrieve_ms for r in valid]) if valid else 0
    _log(f"\n平均延遲:  encode={avg_enc:.1f}ms  retrieve={avg_ret:.1f}ms")
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

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    detail_path = OUTPUTS_DIR / "retrieval_results.csv"
    detail_f = open(detail_path, "w", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(detail_f, fieldnames=DETAIL_FIELDS)
    writer.writeheader()

    all_results: list[_Result] = []
    theme_counter: Counter = Counter()
    t_pipeline = time.perf_counter()

    for idx, sf in enumerate(structured_files):
        news = _load_news(sf)
        if news is None:
            _log(f"  [{idx+1}/{len(structured_files)}] SKIP: {sf.name}")
            continue

        _log(f"  [{idx+1}/{len(structured_files)}] {news.news_id} — {news.title[:40]}…")

        res = _run_retrieval(news, model)
        all_results.append(res)

        for routed in res.output.routed_themes:
            theme_counter[routed] += 1

        themes_str = "; ".join(news.themes)

        if res.error:
            writer.writerow({
                "news_id": news.news_id, "title": news.title,
                "themes": themes_str, "rank": 0,
                "law_name": f"ERROR: {res.error}",
                "article_number": "", "similarity": "", "distance": "",
                "routed_theme": "", "article_text": "",
            })
            continue

        for rank, r in enumerate(res.output.results, 1):
            writer.writerow({
                "news_id": news.news_id, "title": news.title,
                "themes": themes_str, "rank": rank,
                "law_name": r.law_name, "article_number": r.article_number,
                "similarity": f"{r.similarity:.4f}",
                "distance": f"{r.distance:.4f}",
                "routed_theme": r.theme, "article_text": r.text,
            })

    detail_f.close()
    total_time = time.perf_counter() - t_pipeline

    _log(f"\n結果 → {detail_path}")
    _print_summary(all_results, theme_counter, total_time)


if __name__ == "__main__":
    main()
