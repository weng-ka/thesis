# bench03：RAG 摘要 vs bench01 指標對比

## 入口

```bash
python3 srcs/scripts/bench_03_compare_summaries.py
```

## 輸入

- 參考（偽 gold）：`intermediate/benchmark_bench01/bench01_<序號>_<news_id>_…_reference.md`
- 系統摘要：`intermediate/rag_model_compare_bench02/<模型>/summary/bench02_<序號>_<news_id>_rag.md`

以 `(序號, news_id)` 對齊；僅計算**兩邊皆存在**的篇數。

## 指標（整體）

| 指標 | 聚合方式 |
|------|----------|
| BLEU-1、BLEU-4 | **Corpus BLEU**（**jieba 詞級** token），NLTK + smoothing method1 |
| ROUGE-1、ROUGE-2、ROUGE-L | **Macro**：逐篇 F1，再對篇數平均；**jieba 分詞** + `RougeScorer` 自訂 `JiebaTokenizer`（避免預設 tokenizer 丟棄中文） |

預設模型：`qwen-max`、`glm-5`、`deepseek-v3`（`--models` 可改）。

## 輸出

- `intermediate/outputs/bench03_compare_metrics.json`（含逐篇 ROUGE）
- `intermediate/outputs/bench03_compare_table.md`（總表）
- `experiment/bench03_run_<UTC>.json`

依賴：`nltk`、`rouge-score`、`jieba`（見 `requirements.txt`）。
