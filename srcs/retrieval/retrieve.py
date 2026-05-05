"""
基於議題分類的路由檢索模組。

根據新聞的議題分類（themes），路由至對應的法條向量子庫，
以等額分配策略分別檢索候選法條，再跨模塊合併重排序，
返回語義相關性最高的 Top-k 條法條。
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
import numpy as np
from numpy.typing import NDArray

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "srcs"))

from config.paths import LAW_VECTORDB_DIR
from config.theme_law_mapping import (
    THEME_TO_COLLECTION,
    normalize_theme,
)
from retrieval.query import build_query_text, encode_query, load_embedding_model

_chroma_client_cache: dict[str, chromadb.ClientAPI] = {}


@dataclass
class LawArticleResult:
    """單條法條檢索結果。"""

    law_id: str
    law_name: str
    article_number: str
    article_index: int
    text: str
    distance: float
    theme: str

    @property
    def similarity(self) -> float:
        """ChromaDB cosine distance → cosine similarity。"""
        return 1.0 - self.distance


@dataclass
class RetrievalOutput:
    """完整檢索輸出，包含結果與路由元資訊。"""

    results: list[LawArticleResult] = field(default_factory=list)
    routed_themes: list[str] = field(default_factory=list)
    skipped_themes: list[str] = field(default_factory=list)
    per_theme_k: int = 0
    top_k: int = 0


def _get_chroma_client(db_dir: Path = LAW_VECTORDB_DIR) -> chromadb.ClientAPI:
    """載入並快取 ChromaDB client。"""
    key = str(db_dir)
    if key not in _chroma_client_cache:
        _chroma_client_cache[key] = chromadb.PersistentClient(path=key)
    return _chroma_client_cache[key]


def retrieve_laws(
    query_vector: NDArray[np.float32],
    themes: list[str],
    top_k: int = 10,
    db_dir: Path = LAW_VECTORDB_DIR,
) -> RetrievalOutput:
    """
    基於議題路由的法條語義檢索。

    流程：
      1. 正規化 themes → 確定要查詢的 collection
      2. 等額分配：每個子庫檢索 ceil(top_k / n_themes) 條候選
      3. 跨模塊合併，按 cosine distance 升序排序（越小越相似）
      4. 取最終 Top-k 條

    Args:
        query_vector: 正規化後的查詢向量（1-D ndarray）。
        themes: 新聞的議題分類列表（可含簡體/髒數據）。
        top_k: 最終返回的法條數量。
        db_dir: ChromaDB 持久化目錄。

    Returns:
        RetrievalOutput，包含 top_k 條法條及路由元資訊。
    """
    client = _get_chroma_client(db_dir)

    canonical_themes: list[str] = []
    skipped: list[str] = []
    for raw in themes:
        norm = normalize_theme(raw)
        if norm is None:
            skipped.append(raw)
            continue
        if norm not in canonical_themes:
            canonical_themes.append(norm)

    if not canonical_themes:
        return RetrievalOutput(
            skipped_themes=skipped,
            top_k=top_k,
        )

    per_theme_k = math.ceil(top_k / len(canonical_themes))
    all_candidates: list[LawArticleResult] = []

    for theme in canonical_themes:
        col_name = THEME_TO_COLLECTION[theme]
        collection = client.get_collection(name=col_name)

        actual_k = min(per_theme_k, collection.count())
        if actual_k == 0:
            continue

        results = collection.query(
            query_embeddings=[query_vector.tolist()],
            n_results=actual_k,
            include=["documents", "metadatas", "distances"],
        )

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0]

        for doc, meta, dist in zip(docs, metas, dists):
            all_candidates.append(LawArticleResult(
                law_id=meta["law_id"],
                law_name=meta["law_name"],
                article_number=meta["article_number"],
                article_index=meta["article_index"],
                text=doc,
                distance=dist,
                theme=theme,
            ))

    all_candidates.sort(key=lambda r: r.distance)
    final = all_candidates[:top_k]

    return RetrievalOutput(
        results=final,
        routed_themes=canonical_themes,
        skipped_themes=skipped,
        per_theme_k=per_theme_k,
        top_k=top_k,
    )


def format_retrieved_laws(output: RetrievalOutput) -> str:
    """
    將檢索結果格式化為可直接輸入摘要生成模組的法條文本。

    Args:
        output: retrieve_laws 的輸出。

    Returns:
        格式化後的法條文本字串。
    """
    if not output.results:
        return ""

    lines: list[str] = []
    for i, r in enumerate(output.results, 1):
        lines.append(
            f"[{i}] 《{r.law_name}》{r.article_number}"
            f"（相似度 {r.similarity:.3f}）\n{r.text}"
        )
    return "\n\n".join(lines)


def _extract_rights_violated(data: dict) -> list[str]:
    """從 structured JSON 的 events 中彙總所有 rights_violated。"""
    items: list[str] = []
    for ev in data.get("events", []):
        items.extend(ev.get("worker_situation", {}).get("rights_violated", []))
    return items


def retrieve_laws_for_article(
    structured: dict,
    top_k: int = 10,
    model: object | None = None,
) -> str:
    """
    端到端便利函式：從 structured JSON 直接取得格式化法條文本。

    內部串接 build_query_text → encode_query → retrieve_laws → format。

    Args:
        structured: extract_schema 產出的完整結構化 dict。
        top_k: 最終返回的法條數量。
        model: 已載入的 SentenceTransformer；為 None 則自動載入。

    Returns:
        格式化後的法條文本字串，可直接輸入摘要 prompt。
    """
    five_w1h = structured.get("5W1H", {})
    themes = structured.get("themes", [])
    rights_violated = _extract_rights_violated(structured)

    query_text = build_query_text(five_w1h, rights_violated)

    if model is None:
        model = load_embedding_model()
    query_vector = encode_query(query_text, model=model)

    output = retrieve_laws(query_vector, themes, top_k=top_k)
    return format_retrieved_laws(output)
