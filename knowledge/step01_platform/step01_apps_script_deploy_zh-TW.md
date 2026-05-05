# Step1c：Apps Script Web App 部署指引（需自行在 Google 完成）

## 是否能在本 repo「自動部署」？

**不能。** Web App 的執行身分、試算表存取權、首次 OAuth 授權、公開網址都綁在你的 Google 帳號；Cursor 無法替你完成這一步。  
本目錄提供的 `step01_apps_script_Code.gs` 可直接貼到 Apps Script 編輯器，再依下列步驟部署。

---

## 前置（你已完成 Step1b）

- 試算表已匯入 `article_id, raw_title, raw_text, summary_raw, summary_structured, summary_rag`（與 `intermediate/step01_platform/step01_google_sheet_articles_30.csv` 一致）。
- Session 清單已與 `intermediate/step00_sampling/step00_sessions_10x12.json` 一致（腳本內嵌 `S001`–`S010`；若你改過分配，須同步改 `.gs` 的 `SESSIONS`）。

---

## 操作步驟（字面順序）

### 1. 建立綁定試算表的專案

1. 開啟你的 **Google 試算表**（裝載 30 篇該表）。
2. 選單 **擴充功能 → Apps Script**。
3. 刪除預設 `程式碼.gs` 內容，將本目錄 **`step01_apps_script_Code.gs` 全文貼上**（或保留檔名為 `Code.gs` 亦可）。
4. 在 `Code.gs` 最上方 `CONFIG` 內設定 **`SPREADSHEET_ID`**（強烈建議）：從試算表網址 `.../d/<ID>/...` 複製 `<ID>` 貼上。
5. 左上角 **儲存專案**（建議專案命名：`thesis-step01-platform`）。

### 2. 授權

1. 在編輯器選 **執行**（可先選任一函式，例如不執行也可直接部署時觸發）。
2. 第一次會要求 **審查權限** → 選你的 Google 帳號 → **進階** → **前往…（不安全）**（若顯示）→ 允許存取試算表。

### 3. 部署為 Web 應用程式

1. 右上角 **部署 →新增部署作業**。
2. 類型選 **網路應用程式**。
3. 建議設定：
   - **說明**：`step01 v1`（日後改版可再新增部署版本）。
   - **執行身分**：**我**。
   - **具有存取權的使用者**：**任何人**（含匿名），否則 GitHub Pages 上的前端無法呼叫。
4. **部署** → 複製 **網路應用程式 URL**（格式類似 `https://script.google.com/macros/s/.../exec`）。此即前端 `fetch` 的基底網址。


### 4. 驗證 API（瀏覽器或 curl）

**GET session（建議用 path 版，避免 query 在某些環境被 Google 擋下）**

```text
https://script.google.com/macros/s/AKfycbwV1Ry2ox0zvSU8pY_4oJ7fjMmhyOrW24Hj_SaTRxWZWGTp6aI03z6_sqRvTGXRZeqJuw/exec/session/S001
```

預期：JSON，`ok: true`，內含 `assigned_articles`、`articles`（每篇含 `summaries` 的 A/B/C 與 `ab_mapping`）。

若你看到瀏覽器回傳 HTML 類似 **`Sorry, unable to open the file at present.`**，通常代表腳本在 Web App 執行時打不開試算表（常見原因：未設定 `SPREADSHEET_ID` / 權限未授權 / 不是你預期的那份 Sheet）。請先設定 `SPREADSHEET_ID` 後重新部署，再測一次。

**POST submit（對應 `POST /api/submit`）**

```bash
curl -sS -X POST 'https://script.google.com/macros/s/AKfycbwV1Ry2ox0zvSU8pY_4oJ7fjMmhyOrW24Hj_SaTRxWZWGTp6aI03z6_sqRvTGXRZeqJuw/exec' \
  -H 'Content-Type: application/json' \
  -d '{"api":"submit","session_id":"S001","participant_id":"test","responses":{},"secret":null}'
```

（若未設定指令碼屬性 `SUBMIT_SECRET`，可不帶 `secret`。）  
預期：`ok: true` 與 `submission_id`。同一 `session_id` 第二次 POST 應回 `already_submitted`。

### 6. 實驗紀錄（repo）

部署完成後，在 **`experiment/`** 新增一筆（檔名含步驟號與時間），例如：

- `experiment/step01_platform_apps_script_deploy_20260505T120000Z.json`

內容至少含：`webapp_url`（可打馬後存）、`deploy_version` 說明、`data_version`（與腳本 `CONFIG.DATA_VERSION`）、`sheet_id` 是否記錄、是否啟用 `SUBMIT_SECRET`。

---

## 與 REST 路徑的對應說明

Google Apps Script **只有一個** `/exec` URL，沒有真正的 `/api/session` 路徑路由；本腳本約定：

| MVP        | 實際呼叫 |
|-----------|----------|
| GET /api/session?sid= | `GET .../exec/session/S001`（建議）<br>（備用）`GET .../exec?api=session&sid=S001` |
| POST /api/submit     | `POST .../exec`，Body JSON 第一層含 `"api":"submit"` |

前端 Step1d 實作時請依上表拼接（或在 axios 封裝一層）。

---

## CORS / 跨網域

若 GitHub Pages 前端 `fetch` 被瀏覽器擋 CORS，請先確認部署為 **任何人** 可存取；若仍失敗，再排查瀏覽器 Console。常見緩解是同網域代理（另議）；多數情況正確部署即可。

---

## 維護函式

- **`resetSessionPermAndSubmission('S001')`**：清除該 session 的 A/B/C 快取與「已提交」旗標（僅測試時用，勿讓受試者濫用）。

---

## 相關檔案

- 原始碼：`knowledge/step01_platform/step01_apps_script_Code.gs`
- 資料契約（建議後續補）：`knowledge/step01_platform/step01_data_contract.md`
