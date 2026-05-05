"""
裝置選擇工具。

依序檢查 CUDA → MPS → CPU，也可透過環境變數 DEVICE 強制指定。
"""

from __future__ import annotations

import os


def get_device(prefer: str = "auto") -> str:
    """
    回傳最適合的 PyTorch 裝置名稱。

    優先順序：環境變數 DEVICE > prefer 參數 > CUDA > MPS > CPU。

    Args:
        prefer: 指定裝置（"cuda" / "mps" / "cpu"），
                或 "auto" 自動偵測。

    Returns:
        裝置名稱字串，可直接傳入 torch / SentenceTransformer。
    """
    env_device = os.environ.get("DEVICE", "").strip().lower()
    if env_device:
        return env_device

    if prefer != "auto":
        return prefer

    import torch

    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"
