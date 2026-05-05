/**
 * Step01c — Google Apps Script Web App（綁定試算表）
 *
 * 契約（與 MVP / CSV 一致）：
 * - 試算表第一個工作表（或可改名，見 CONFIG.ARTICLES_SHEET_NAME）第 1 列為表頭：
 *   article_id, raw_title, raw_text, summary_raw, summary_structured, summary_rag
 * - Session 清單內嵌於下方 SESSIONS（來源：intermediate/step00_sampling/step00_sessions_10x12.json）
 *
 * HTTP 介面（GAS 單一 Web App URL，以 query / JSON 區分「類 REST」行為）：
 * - GET  取得 session： .../exec?api=session&sid=S001
 * - POST 提交：        Body 為 JSON，需含 "api":"submit" 與其餘 payload
 *
 * 行為：session 白名單、每位 session 首次 GET 時固化 A/B/C ↔ 三版本對應並快取、同一 session 僅接受一次 POST。
 */
var CONFIG = {
  // 強烈建議設定：避免 Web App 環境下抓不到 active spreadsheet
  // 取值方式：從試算表網址中 /d/<ID>/ 複製 <ID>
  SPREADSHEET_ID: '1WUyMBkE5i9z5Jn6dYrZ_6u0RM1l-GDC0CjAOsQrLChY',
  ARTICLES_SHEET_NAME: '', // 空字串 = 使用試算表第一個工作表
  SUBMISSIONS_SHEET_NAME: 'step01_submissions',
  DATA_VERSION: 'step00_sessions_10x12_v1',
  // 可選：在「專案設定 → 指令碼屬性」設定 SUBMIT_SECRET；POST body 帶同名字段則比對
};

/** @type {Object<string, string[]>} 與 repo 內 step00_sessions_10x12.json 之 sessions 一致 */
var SESSIONS = {
  S001: ['0003', '0047', '0008', '0048', '0088', '0110', '0118', '0119', '0010', '0006', '0007', '0014'],
  S002: ['0019', '0027', '0028', '0031', '0104', '0055', '0073', '0075', '0076', '0083', '0084', '0102'],
  S003: ['0116', '0120', '0123', '0128', '0130', '0132', '0003', '0047', '0008', '0048', '0088', '0110'],
  S004: ['0118', '0119', '0010', '0006', '0007', '0014', '0019', '0027', '0028', '0031', '0104', '0055'],
  S005: ['0073', '0075', '0076', '0083', '0084', '0102', '0116', '0120', '0123', '0128', '0130', '0132'],
  S006: ['0003', '0047', '0008', '0048', '0088', '0110', '0118', '0119', '0010', '0006', '0007', '0014'],
  S007: ['0019', '0027', '0028', '0031', '0104', '0055', '0073', '0075', '0076', '0083', '0084', '0102'],
  S008: ['0116', '0120', '0123', '0128', '0130', '0132', '0003', '0047', '0008', '0048', '0088', '0110'],
  S009: ['0118', '0119', '0010', '0006', '0007', '0014', '0019', '0027', '0028', '0031', '0104', '0055'],
  S010: ['0073', '0075', '0076', '0083', '0084', '0102', '0116', '0120', '0123', '0128', '0130', '0132'],
};

var PROP_PERM_PREFIX = 'step01_perm_';
var PROP_SUBMITTED_PREFIX = 'step01_submitted_';

function doGet(e) {
  // 避免某些環境對 query 參數直接回 400（Google 層擋下）
  // 改用 path 路由：
  // - /exec/ping
  // - /exec/session/S001
  var path = (e && e.pathInfo ? String(e.pathInfo) : '').replace(/^\/+/, '');
  var parts = path ? path.split('/') : [];
  var head = (parts[0] || '').toLowerCase();

  if (head === 'ping') {
    return jsonOutput_({ ok: true, pong: true, ts: new Date().toISOString() });
  }

  if (head === 'session') {
    var sid = String(parts[1] || '').trim().toUpperCase();
    return jsonOutput_(buildSessionPayload_(sid));
  }

  // fallback：仍保留原本 query 方式（若未被擋可用）
  return handleRequest_('GET', e, null);
}

function doPost(e) {
  var body = {};
  try {
    if (e.postData && e.postData.contents) {
      // 1) JSON body (curl / server-side)
      body = JSON.parse(e.postData.contents);
    }
  } catch (err) {
    // 2) Form submission (browser <form>) — avoids CORS/preflight issues on GitHub Pages.
    // Expected fields:
    // - api=submit
    // - payload=<JSON string>
    try {
      var parsed = parseFormBody_(e && e.postData ? e.postData.contents : '');
      if (parsed && parsed.payload) {
        body = JSON.parse(parsed.payload);
      } else {
        body = parsed || {};
      }
    } catch (err2) {
      return jsonOutput_({ ok: false, error: 'invalid_body', detail: String(err2) });
    }
  }
  return handleRequest_('POST', e, body);
}

function parseFormBody_(contents) {
  var s = String(contents || '');
  if (!s) return {};
  var out = {};
  var parts = s.split('&');
  for (var i = 0; i < parts.length; i++) {
    var kv = parts[i].split('=');
    var k = decodeURIComponent(kv[0] || '').trim();
    if (!k) continue;
    var v = decodeURIComponent((kv[1] || '').replace(/\+/g, ' '));
    out[k] = v;
  }
  return out;
}

function handleRequest_(method, e, body) {
  try {
    if (method === 'GET') {
      var api = (e.parameter.api || '').toLowerCase();
      var sid = (e.parameter.sid || '').trim().toUpperCase();
      if (api === 'session' || api === 'api/session') {
        return jsonOutput_(buildSessionPayload_(sid));
      }
      return jsonOutput_({
        ok: false,
        error: 'bad_request',
        hint: 'Use ?api=session&sid=S001',
      });
    }
    if (method === 'POST') {
      var apiPost = (body.api || '').toLowerCase();
      if (apiPost === 'submit' || apiPost === 'api/submit') {
        return jsonOutput_(handleSubmit_(body));
      }
      return jsonOutput_({ ok: false, error: 'bad_request', hint: 'Set body.api to "submit"' });
    }
  } catch (err) {
    return jsonOutput_({ ok: false, error: 'server_error', detail: String(err) });
  }
  return jsonOutput_({ ok: false, error: 'method_not_handled' });
}

function jsonOutput_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function buildSessionPayload_(sid) {
  if (!SESSIONS[sid]) {
    return { ok: false, error: 'unknown_session', sid: sid };
  }
  var ids = SESSIONS[sid];
  var props = PropertiesService.getScriptProperties();
  var cacheKey = PROP_PERM_PREFIX + sid;
  var cached = props.getProperty(cacheKey);
  var permByArticle = cached ? JSON.parse(cached) : {};

  var sheet = getArticlesSheet_();
  var byId = loadArticlesIndex_(sheet);

  var articles = [];
  for (var i = 0; i < ids.length; i++) {
    var aid = normalizeArticleId_(ids[i]);
    var row = byId[aid];
    if (!row) {
      return { ok: false, error: 'article_not_in_sheet', article_id: aid };
    }
    if (!permByArticle[aid]) {
      permByArticle[aid] = makePermForRow_(row);
    }
    var p = permByArticle[aid];
    articles.push({
      article_id: aid,
      raw_title: row.raw_title,
      raw_text: row.raw_text,
      summaries: p.summariesABC,
      ab_mapping: p.ab_mapping,
    });
  }
  props.setProperty(cacheKey, JSON.stringify(permByArticle));

  return {
    ok: true,
    session_id: sid,
    assigned_articles: ids,
    articles: articles,
    data_version: CONFIG.DATA_VERSION,
  };
}

function makePermForRow_(row) {
  var triple = [
    { key: 'raw', text: row.summary_raw },
    { key: 'structured', text: row.summary_structured },
    { key: 'rag', text: row.summary_rag },
  ];
  shuffleArray_(triple);
  var summariesABC = {
    A: triple[0].text,
    B: triple[1].text,
    C: triple[2].text,
  };
  var ab_mapping = {
    A: triple[0].key,
    B: triple[1].key,
    C: triple[2].key,
  };
  return { summariesABC: summariesABC, ab_mapping: ab_mapping };
}

function shuffleArray_(arr) {
  for (var i = arr.length - 1; i > 0; i--) {
    var j = Math.floor(Math.random() * (i + 1));
    var t = arr[i];
    arr[i] = arr[j];
    arr[j] = t;
  }
}

function getArticlesSheet_() {
  var ss = null;
  if (CONFIG.SPREADSHEET_ID) {
    ss = SpreadsheetApp.openById(CONFIG.SPREADSHEET_ID);
  } else {
    ss = SpreadsheetApp.getActiveSpreadsheet();
  }
  if (!ss) {
    throw new Error(
      'Cannot open spreadsheet. Set CONFIG.SPREADSHEET_ID (recommended) or bind script to the target Google Sheet.'
    );
  }
  if (CONFIG.ARTICLES_SHEET_NAME) {
    var sh = ss.getSheetByName(CONFIG.ARTICLES_SHEET_NAME);
    if (!sh) {
      throw new Error('Sheet not found: ' + CONFIG.ARTICLES_SHEET_NAME);
    }
    return sh;
  }
  return ss.getSheets()[0];
}

function loadArticlesIndex_(sheet) {
  var data = sheet.getDataRange().getValues();
  if (data.length < 2) {
    throw new Error('Articles sheet has no data rows.');
  }
  var header = data[0].map(function (h) {
    return String(h).trim();
  });
  var idx = {};
  for (var c = 0; c < header.length; c++) {
    idx[header[c]] = c;
  }
  var required = ['article_id', 'raw_title', 'raw_text', 'summary_raw', 'summary_structured', 'summary_rag'];
  for (var r = 0; r < required.length; r++) {
    if (idx[required[r]] === undefined) {
      throw new Error('Missing column: ' + required[r]);
    }
  }
  var map = {};
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    var id = normalizeArticleId_(row[idx['article_id']]);
    if (!id) continue;
    map[id] = {
      raw_title: String(row[idx['raw_title']] || ''),
      raw_text: String(row[idx['raw_text']] || ''),
      summary_raw: String(row[idx['summary_raw']] || ''),
      summary_structured: String(row[idx['summary_structured']] || ''),
      summary_rag: String(row[idx['summary_rag']] || ''),
    };
  }
  return map;
}

/**
 * Google Sheet 匯入 CSV 時常把 `0003` 變成數字 `3`。
 * 本專案 article_id 以 4 位數字字串為準，這裡做補零正規化。
 */
function normalizeArticleId_(v) {
  if (v === null || v === undefined) return '';
  var s = String(v).trim();
  if (!s) return '';
  if (/^\\d+$/.test(s)) {
    var n = parseInt(s, 10);
    if (isNaN(n)) return '';
    s = String(n);
    while (s.length < 4) s = '0' + s;
    return s;
  }
  return s;
}

function handleSubmit_(body) {
  var secret = PropertiesService.getScriptProperties().getProperty('SUBMIT_SECRET');
  if (secret && body.secret !== secret) {
    return { ok: false, error: 'forbidden', detail: 'secret_mismatch' };
  }

  var sid = String(body.session_id || '').trim().toUpperCase();
  if (!SESSIONS[sid]) {
    return { ok: false, error: 'unknown_session', sid: sid };
  }

  var props = PropertiesService.getScriptProperties();
  // MVP 調整：允許同一個 session 重複提交（你自行在分析時用 payload 區分測試/正式）。
  // 因此不再檢查 step01_submitted_<sid> 旗標，也不再阻擋 already_submitted。

  var payloadStr = JSON.stringify(body);
  var submissionId = Utilities.getUuid();
  var savedAt = new Date().toISOString();

  appendSubmissionRow_(submissionId, savedAt, sid, body.participant_id || '', payloadStr);

  // 保留 perm 快取（A/B/C 對應）即可；submitted flag 不再使用。

  return {
    ok: true,
    submission_id: submissionId,
    saved_at: savedAt,
    session_id: sid,
  };
}

/**
 * 測試用：清空所有 session 的「已提交」旗標（不會刪掉 submissions sheet 既有列）
 * 在 Apps Script 編輯器直接執行 resetAllSessionsSubmittedFlag()
 */
function resetAllSessionsSubmittedFlag() {
  var props = PropertiesService.getScriptProperties();
  for (var sid in SESSIONS) {
    props.deleteProperty(PROP_SUBMITTED_PREFIX + sid);
  }
}

/**
 * 測試用：清空 step01 相關所有 Script Properties（含 perm / submitted）。
 * 在 Apps Script 編輯器直接執行 resetAllStep01ScriptProperties()
 */
function resetAllStep01ScriptProperties() {
  var props = PropertiesService.getScriptProperties();
  var all = props.getProperties();
  for (var k in all) {
    if (k.indexOf('step01_') === 0) props.deleteProperty(k);
  }
}

function appendSubmissionRow_(submissionId, savedAt, sessionId, participantId, payloadJson) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(CONFIG.SUBMISSIONS_SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(CONFIG.SUBMISSIONS_SHEET_NAME);
    sh.appendRow(['submission_id', 'saved_at', 'session_id', 'participant_id', 'payload_json']);
  }
  sh.appendRow([submissionId, savedAt, sessionId, participantId, payloadJson]);
}

/**
 * 一次性維護：若你更新 SESSIONS 或想重跑某 session 的 A/B/C，在編輯器執行
 * resetSessionPermAndSubmission('S001')
 */
function resetSessionPermAndSubmission(sid) {
  sid = String(sid).trim().toUpperCase();
  var props = PropertiesService.getScriptProperties();
  props.deleteProperty(PROP_PERM_PREFIX + sid);
  props.deleteProperty(PROP_SUBMITTED_PREFIX + sid);
}
