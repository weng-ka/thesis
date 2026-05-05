"""
專案路徑集中管理。

所有路徑皆以 PROJECT_ROOT 為基準，確保無論 CWD 在哪都能正確解析。
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── 資料目錄 ──
DATA_DIR = PROJECT_ROOT / "data"

LAW_CORPUS_DIR = DATA_DIR / "law_corpus"
LAW_RAW_DIR = LAW_CORPUS_DIR / "raw"
LAW_SEGMENTED_DIR = LAW_CORPUS_DIR / "segmented"
LAW_VECTORDB_DIR = LAW_CORPUS_DIR / "vectordb"

NEWS_DATASET_DIR = DATA_DIR / "news_dataset"
NEWS_RAW_DIR = NEWS_DATASET_DIR / "raw"
NEWS_STRUCTURED_DIR = NEWS_DATASET_DIR / "structured"

# ── 實驗產物（向量庫以外的執行輸出、日誌）──
INTERMEDIATE_DIR = PROJECT_ROOT / "intermediate"
OUTPUTS_DIR = INTERMEDIATE_DIR / "outputs"
LOG_DIR = INTERMEDIATE_DIR / "logs"

# ── 其他 ──
SRCS_DIR = PROJECT_ROOT / "srcs"
# 保留舊名稱，避免既有 import 斷掉（目前 canonical 為 srcs）
SRC_DIR = SRCS_DIR
