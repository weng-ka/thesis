"""
查詢文本構建與向量化模組。

提供三種查詢模式供實驗比較：
  - 5w1h_only:        僅使用 5W1H 結構化特徵
  - 5w1h_with_body:   使用 5W1H 結構化特徵 + 原始新聞正文
  - 5w1h_with_rights: 使用 5W1H 結構化特徵 + rights_violated 權益問題描述
"""

from __future__ import annotations

import os
import sys
from enum import Enum
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.device import get_device

DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_MODEL_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
MAX_TOKENS = 8192

_model_cache: dict[str, SentenceTransformer] = {}
_tokenizer_cache: dict[str, AutoTokenizer] = {}


class QueryMode(str, Enum):
    """查詢文本構建模式。"""

    FIVE_W1H_ONLY = "5w1h_only"
    FIVE_W1H_WITH_BODY = "5w1h_with_body"
    FIVE_W1H_WITH_RIGHTS = "5w1h_with_rights"


def _get_tokenizer(model_name: str = DEFAULT_MODEL) -> AutoTokenizer:
    """載入並快取 tokenizer。"""
    if model_name not in _tokenizer_cache:
        _tokenizer_cache[model_name] = AutoTokenizer.from_pretrained(
            model_name, revision=DEFAULT_MODEL_REVISION,
        )
    return _tokenizer_cache[model_name]


def _truncate_body(
    body: str,
    w1h_block: str,
    model_name: str = DEFAULT_MODEL,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """
    截斷正文，使「正文 + 分隔符 + 5W1H」的總 token 數不超過上限。

    保留 5W1H 完整，僅對正文做尾部截斷。
    """
    tokenizer = _get_tokenizer(model_name)
    separator = "\n\n"
    overhead_tokens = len(tokenizer.encode(separator + w1h_block, add_special_tokens=True))
    body_budget = max_tokens - overhead_tokens

    if body_budget <= 0:
        return ""

    body_ids = tokenizer.encode(body, add_special_tokens=False)
    if len(body_ids) <= body_budget:
        return body

    truncated_ids = body_ids[:body_budget]
    return tokenizer.decode(truncated_ids, skip_special_tokens=True)


def build_query_text(
    five_w1h: dict[str, str],
    body: str = "",
    mode: QueryMode = QueryMode.FIVE_W1H_ONLY,
    model_name: str = DEFAULT_MODEL,
    max_tokens: int = MAX_TOKENS,
    rights_violated: list[str] | None = None,
) -> str:
    """
    將結構化特徵（及可選的正文/權益描述）拼接為檢索用查詢文本。

    Args:
        five_w1h: 5W1H dict，包含 who/what/when/where/why/how。
        body: 原始新聞正文。僅在 5w1h_with_body 模式下使用。
        mode: 查詢模式。
        model_name: 用於 tokenizer 計算 token 數的模型名稱。
        max_tokens: 查詢文本的最大 token 數。
        rights_violated: 權益問題描述列表。僅在 5w1h_with_rights 模式下使用。

    Returns:
        拼接後的查詢文本字串。
    """
    w1h_block = (
        f"涉及主體：{five_w1h.get('who', '')}\n"
        f"事件內容：{five_w1h.get('what', '')}\n"
        f"發生時間：{five_w1h.get('when', '')}\n"
        f"發生地點：{five_w1h.get('where', '')}\n"
        f"事件原因：{five_w1h.get('why', '')}\n"
        f"事件經過：{five_w1h.get('how', '')}"
    )

    if mode == QueryMode.FIVE_W1H_ONLY:
        return w1h_block

    if mode == QueryMode.FIVE_W1H_WITH_RIGHTS:
        items = [r for r in (rights_violated or []) if r.strip()]
        if not items:
            return w1h_block
        rights_block = "涉及權益問題：" + "；".join(items)
        return f"{w1h_block}\n{rights_block}"

    trimmed = body.strip()
    if not trimmed:
        return w1h_block

    trimmed = _truncate_body(trimmed, w1h_block, model_name, max_tokens)
    return f"{trimmed}\n\n{w1h_block}" if trimmed else w1h_block


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
    vec = model.encode(query_text, normalize_embeddings=True)
    return vec
