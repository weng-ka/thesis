# 勞工新聞 × 勞動法條 RAG 檢索系統

基於 5W1H 結構化特徵的新聞—法條語意檢索實驗。

## 環境資訊

| 項目 | 版本 / 規格 |
|------|------------|
| OS | macOS 15.7.3 (arm64) |
| CPU | Apple M1 Pro |
| GPU | Apple M1 Pro (16-core GPU, Metal 3) |
| Python | 3.11.14 |
| 套件管理 | conda (`thesis` 環境) |
| Embedding 模型 | `BAAI/bge-m3` |
| 推論裝置 | MPS (Apple Silicon) / CUDA / CPU（自動偵測） |

## 快速開始

```bash
# 1. 建立並啟用 conda 環境
conda create -n thesis python=3.11 -y
conda activate thesis

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 設定環境變數
cp .env.example .env
# 編輯 .env，填入 API key 等

# 4. 強制指定推論裝置（可選）
export DEVICE=cpu  # 或 cuda / mps
```

## 專案結構

根目錄僅保留六個工作目錄與設定／依賴檔案：

```
├── data/              # 法條與新聞語料（raw / segmented / structured / vectordb 等）
├── docs/              # 論文與進度文件
├── experiments/       # 實驗腳本或批次設定（自訂）
├── intermediate/      # 執行產物：outputs/（CSV、摘要 md）、logs/（如 extract_errors.log）
├── knowledge/         # 外部知識或參考資料（自訂）
├── src/
│   ├── config/        # 路徑、裝置、議題映射
│   ├── prompts/
│   ├── retrieval/
│   ├── scripts/
│   ├── schema/
│   └── tests/         # pytest
├── .env.example
├── pytest.ini
├── requirements.txt
└── README.md
```

## 可復現性說明

- 裝置選擇透過 `src/config/device.py` 統一管理，支援 CUDA → MPS → CPU 自動偵測，也可透過環境變數 `DEVICE` 強制指定
- 所有路徑透過 `src/config/paths.py` 集中定義，不依賴工作目錄；管線輸出與日誌寫入 `intermediate/`，不與 `data/` 混放
- Embedding 模型為 `BAAI/bge-m3`，建議記錄使用時的 model revision（`git log` on HuggingFace Hub）

測試：`pytest`（設定見 `pytest.ini`）
