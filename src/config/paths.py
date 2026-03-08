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

# ── 其他 ──
LOG_DIR = PROJECT_ROOT / "logs"
SRC_DIR = PROJECT_ROOT / "src"
