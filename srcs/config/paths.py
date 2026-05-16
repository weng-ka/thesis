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

# ── Step02：結構化抽取品質驗證 ──
STEP02_DIR = INTERMEDIATE_DIR / "step02_extraction_quality"
STEP02_SAMPLE_MANIFEST = STEP02_DIR / "step02_sampled_50.json"
STEP02_FIELD_ROWS = STEP02_DIR / "step02_field_rows.jsonl"
STEP02_JUDGMENTS_JSONL = STEP02_DIR / "step02_judgments.jsonl"
STEP02_FIELD_JUDGMENTS_CSV = STEP02_DIR / "step02_field_judgments.csv"
STEP02_FIELD_ACCURACY_SUMMARY_CSV = STEP02_DIR / "step02_field_accuracy_summary.csv"
STEP02_METRICS_OVERALL_JSON = STEP02_DIR / "step02_metrics_overall.json"

# ── Step03：法條檢索策略對比 ──
STEP03_DIR = INTERMEDIATE_DIR / "step03_retrieval_eval"
STEP03_SAMPLE_MANIFEST = STEP03_DIR / "step03_sample_manifest.json"
STEP03_RETRIEVAL_HITS = STEP03_DIR / "step03_retrieval_hits.jsonl"
STEP03_RELEVANCE_SCORES_JSONL = STEP03_DIR / "step03_relevance_scores.jsonl"
STEP03_RELEVANCE_SCORES_CSV = STEP03_DIR / "step03_relevance_scores.csv"
STEP03_STRATEGY_METRICS_CSV = STEP03_DIR / "step03_strategy_metrics.csv"
STEP03_METRICS_OVERALL_JSON = STEP03_DIR / "step03_metrics_overall.json"

EXPERIMENT_DIR = PROJECT_ROOT / "experiment"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"

# ── 其他 ──
SRCS_DIR = PROJECT_ROOT / "srcs"
# 保留舊名稱，避免既有 import 斷掉（目前 canonical 為 srcs）
SRC_DIR = SRCS_DIR
