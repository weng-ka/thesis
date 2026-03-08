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

```
├── data/
│   ├── law_corpus/        # 法條語料
│   │   ├── raw/           # 原始法條文本
│   │   ├── segmented/     # 切條後 JSON
│   │   └── vectordb/      # ChromaDB 向量庫
│   └── news_dataset/      # 新聞資料集
│       ├── raw/           # 原始新聞 TXT
│       └── structured/    # 結構化抽取 JSON
├── src/
│   ├── config/            # 路徑、裝置、議題映射等設定
│   ├── prompts/           # LLM prompt 模板
│   ├── retrieval/         # 查詢向量化模組
│   └── scripts/           # 資料處理腳本
├── tests/
├── requirements.txt
└── README.md
```

## 可復現性說明

- 裝置選擇透過 `src/config/device.py` 統一管理，支援 CUDA → MPS → CPU 自動偵測，也可透過環境變數 `DEVICE` 強制指定
- 所有路徑透過 `src/config/paths.py` 集中定義，不依賴工作目錄
- Embedding 模型為 `BAAI/bge-m3`，建議記錄使用時的 model revision（`git log` on HuggingFace Hub）
