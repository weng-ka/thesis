#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法條向量資料庫建庫腳本。

使用 BAAI/bge-m3 對各法條文本進行 embedding，
按 12 個議題模塊分別建立 ChromaDB collection，持久化至本地。

用法：
  python build_law_vectordb.py [--model BAAI/bge-m3] [--db-dir data/law_corpus/vectordb]

首次執行會自動下載模型（~2GB）。建庫完成後可重複執行，會清空舊資料重建。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ["PYTHONUNBUFFERED"] = "1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import chromadb
from sentence_transformers import SentenceTransformer

from config.device import get_device
from config.paths import LAW_SEGMENTED_DIR, LAW_VECTORDB_DIR
from config.theme_law_mapping import THEME_LAW_MAPPING, THEME_TO_COLLECTION


def _log(msg: str) -> None:
    """即時輸出日誌（強制 flush）。"""
    print(msg, flush=True)

SEGMENTED_DIR = LAW_SEGMENTED_DIR
DEFAULT_DB_DIR = LAW_VECTORDB_DIR
DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"


def _collection_name(theme: str) -> str:
    """將議題名稱轉為 ChromaDB collection name。"""
    return THEME_TO_COLLECTION[theme]


def _load_articles_by_law_id() -> dict[str, list[dict]]:
    """
    讀取 segmented/ 下所有 law_*.json，按 law_id 分組。

    Returns:
        {law_id: [article_dict, ...]}
    """
    articles_by_id: dict[str, list[dict]] = {}
    for path in sorted(SEGMENTED_DIR.glob("law_*.json")):
        if path.name == "merged_laws.json":
            continue
        with path.open("r", encoding="utf-8") as f:
            articles = json.load(f)
        if not articles:
            continue
        law_id = articles[0]["law_id"]
        articles_by_id[law_id] = articles
    return articles_by_id


def build_vectordb(model_name: str, db_dir: Path) -> None:
    """
    主建庫流程：載入模型 → 讀取法條 → 按議題模塊建立 12 個 collection。

    Args:
        model_name: HuggingFace 模型名稱。
        db_dir: ChromaDB 持久化目錄。
    """
    _log(f"載入 embedding 模型：{model_name}")
    _log("（首次執行需下載模型，約 2GB，請耐心等待...）")
    t0 = time.time()
    device = get_device()
    model = SentenceTransformer(
        model_name, device=device, revision=DEFAULT_MODEL_REVISION,
    )
    _log(f"模型載入完成（{time.time() - t0:.1f}s），裝置：{device}")

    articles_by_id = _load_articles_by_law_id()
    _log(f"已讀取 {sum(len(v) for v in articles_by_id.values())} 條法條"
         f"（{len(articles_by_id)} 部法律）")

    db_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(db_dir))

    total_embedded = 0
    t_all = time.time()

    for theme, law_ids in THEME_LAW_MAPPING.items():
        col_name = _collection_name(theme)

        # 清空舊 collection（如有）再重建
        try:
            client.delete_collection(col_name)
        except Exception:
            pass
        collection = client.create_collection(
            name=col_name,
            metadata={"theme": theme, "hnsw:space": "cosine"},
        )

        # 收集該議題下所有法條
        texts: list[str] = []
        ids: list[str] = []
        metadatas: list[dict] = []

        for law_id in law_ids:
            if law_id not in articles_by_id:
                _log(f"  [WARN] {law_id} 在 segmented/ 中找不到，已跳過")
                continue
            for art in articles_by_id[law_id]:
                doc_id = f"{art['law_id']}_art{art['article_index']:03d}"
                texts.append(art["text"])
                ids.append(doc_id)
                metadatas.append({
                    "law_id": art["law_id"],
                    "law_name": art["law_name"],
                    "article_number": art["article_number"],
                    "article_index": art["article_index"],
                })

        if not texts:
            _log(f"  [{col_name}] {theme}：無法條，跳過")
            continue

        # 批量 embedding
        t1 = time.time()
        embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        embed_time = time.time() - t1

        collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings.tolist(),
            metadatas=metadatas,
        )

        total_embedded += len(texts)
        _log(f"  [{col_name}] {theme}："
             f"{len(texts)} 條法條，embed {embed_time:.1f}s")

    total_time = time.time() - t_all
    _log(f"\n建庫完成：{total_embedded} 條法條 → {len(THEME_LAW_MAPPING)} 個 collection")
    _log(f"總耗時：{total_time:.1f}s")
    _log(f"持久化目錄：{db_dir}")

    _log("\nCollection 對照表：")
    for theme in THEME_LAW_MAPPING:
        _log(f"  {_collection_name(theme)} → {theme}")


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(description="建立法條向量資料庫")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Embedding 模型名稱（預設 {DEFAULT_MODEL}）",
    )
    parser.add_argument(
        "--db-dir", default=str(DEFAULT_DB_DIR),
        help=f"ChromaDB 持久化目錄（預設 {DEFAULT_DB_DIR}）",
    )
    args = parser.parse_args()
    build_vectordb(model_name=args.model, db_dir=Path(args.db_dir))


if __name__ == "__main__":
    main()
