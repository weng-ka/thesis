"""
查詢文本構建與向量化模組。

將 5W1H 結構化特徵與 rights_violated 權益問題描述
拼接為檢索用查詢文本，再透過 BAAI/bge-m3 轉為向量。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "srcs"))

from config.device import get_device

DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"

_model_cache: dict[str, SentenceTransformer] = {}


def build_query_text(
    five_w1h: dict[str, str],
    rights_violated: list[str] | None = None,
) -> str:
    """
    將 5W1H 結構化特徵與權益問題描述拼接為檢索用查詢文本。

    Args:
        five_w1h: 5W1H dict，包含 who/what/when/where/why/how。
        rights_violated: 權益問題描述列表（來自 events[].worker_situation.rights_violated）。

    Returns:
        拼接後的查詢文本字串。
    """
    w1h_block = (
        f"涉及主体：{five_w1h.get('who', '')}\n"
        f"事件内容：{five_w1h.get('what', '')}\n"
        f"发生时间：{five_w1h.get('when', '')}\n"
        f"发生地点：{five_w1h.get('where', '')}\n"
        f"事件原因：{five_w1h.get('why', '')}\n"
        f"事件经过：{five_w1h.get('how', '')}"
    )

    items = [r for r in (rights_violated or []) if r.strip()]
    if not items:
        return w1h_block

    rights_block = "涉及权益问题：" + "；".join(items)
    return f"{w1h_block}\n{rights_block}"


def load_embedding_model(model_name: str = DEFAULT_MODEL) -> SentenceTransformer:
    """
    載入並快取 embedding 模型（同一 model_name 只載入一次）。

    Args:
        model_name: HuggingFace 模型名稱。

    Returns:
        SentenceTransformer 模型實例。
    """
    if model_name not in _model_cache:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        device = get_device()
        _model_cache[model_name] = SentenceTransformer(
            model_name, device=device, revision=DEFAULT_MODEL_REVISION,
        )
    return _model_cache[model_name]


def encode_query(
    query_text: str,
    model: SentenceTransformer | None = None,
    model_name: str = DEFAULT_MODEL,
) -> NDArray[np.float32]:
    """
    將查詢文本轉為正規化向量。

    Args:
        query_text: 由 build_query_text 產生的查詢文本。
        model: 已載入的 SentenceTransformer 實例。若為 None 則自動載入。
        model_name: 當 model 為 None 時使用的模型名稱。

    Returns:
        1-D numpy array（正規化後的查詢向量）。
    """
    if model is None:
        model = load_embedding_model(model_name)
    vec = model.encode(
        query_text,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vec
