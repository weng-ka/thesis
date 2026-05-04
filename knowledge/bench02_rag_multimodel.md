# bench02：多模型 RAG 摘要對照資料

## 流程（每篇 × 每模型）

1. **結構化**：`schema_extraction_prompt` + `extract_schema.merge_result`（metadata 仍由程式預填）。
2. **RAG**：`retrieve_laws_for_article`（Chroma / `build_query_text` 與主專案相同）。
3. **摘要**：`summary_prompt`（`SYSTEM_PROMPT` + `build_user_prompt`）。

**執行順序**：依 raw 排序後的序號，對**同一篇**依序跑完所有模型，再換下一篇（`execution_order: by_article_then_models`）。

同一篇內 **抽取與摘要使用同一 `model` 名**；`LLM_API_KEY`、`LLM_BASE_URL` 僅來自 `.env`。

## 預設模型

`qwen-max`、`glm-5`、`deepseek-v3`（已不含 kimi；可 `--models` 擴充）。

## 目錄

根目錄：`intermediate/rag_model_compare_bench02/<模型名>/`

- `structured/bench02_<序號>_<news_id>_structured.json`
- `summary/bench02_<序號>_<news_id>_rag.md`
- `bench02_manifest.json`（該模型本次條目狀態）

實驗紀錄：`experiment/bench02_run_<UTC>.json`

## 入口

`python3 src/scripts/bench_02_rag_multimodel.py`（預設 raw **前 5 篇** × 上述三模型）

可選：`--limit`、`--models`、`--top-k`、`--overwrite`。

## 與主程式差異

- `summarize_news.py` / `extract_schema.py` 支援可選 `model` 參數；bench02 不改 `.env` 的 `LLM_MODEL`，僅在呼叫時傳入各模型名。
