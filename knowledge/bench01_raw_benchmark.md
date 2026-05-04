# bench01：Raw-only 偽參考摘要（Benchmark 初稿）

## 目的

量化實驗與 RAG 管線隔離：僅用 `summary_prompt_raw_only` 的 system/user prompt，對 `data/news_dataset/raw` 前 N 則 `.txt` 呼叫 **gpt-4o**（程式內固定模型名，由同一中介路由），產出後續 ROUGE 類指標可用的參考文本。

## 環境變數

與主專案相同，僅讀 **`.env`**：

- `LLM_API_KEY`、`LLM_BASE_URL`：與 `summarize_news.py` 等腳本一致。
- 本腳本**不**讀 `LLM_MODEL`；摘要請求一律使用 **`gpt-4o`**（常數 `BENCHMARK_MODEL`），由中介依模型名轉發。

## 產物路徑

- **Benchmark 參考摘要**（本腳本）：`intermediate/benchmark_bench01/bench01_<序號>_<檔幹>_reference.md`
- 清單：`intermediate/benchmark_bench01/bench01_manifest.json`
- **一般 pipeline 摘要**（`summarize_news.py` 等）：`intermediate/outputs/summary_XXXX_*.md`
- 實驗紀錄：`experiment/bench01_run_<UTC時間戳>.json`

腳本入口：`src/scripts/bench_01_build_raw_benchmark.py`
