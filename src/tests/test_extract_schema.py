#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ENV: Thesis
"""
extract_schema pipeline 測試。

使用 tests/fixtures/sample_raw_news.txt 作為真實 raw 新聞範本，
驗證 metadata 解析、內容解析、prompt 組裝、dry-run 等核心環節。

執行：
  pytest src/tests/test_extract_schema.py -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from prompts.schema_extraction_prompt import SYSTEM_PROMPT, build_user_prompt
from scripts.extract_schema import (
    _strip_json_comments,
    call_llm,
    extract_single,
    merge_result,
    parse_raw_content,
)
from scripts.parse_raw_metadata import parse_raw_metadata

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_raw_news.txt"
FIXTURE_CONTENT = FIXTURE_PATH.read_text(encoding="utf-8")
FIXTURE_FILENAME = "0005_恶意欠薪84755元，一服饰厂老板逃匿外地被警方抓获.txt"


# ---------------------------------------------------------------------------
# parse_raw_metadata
# ---------------------------------------------------------------------------


class TestParseRawMetadata:
    """測試 raw 元數據解析。"""

    def test_basic_fields(self):
        """確認 date / source / author 正確解析。"""
        meta = parse_raw_metadata(FIXTURE_CONTENT)
        assert meta is not None
        assert meta.date == "2026-03-03"
        assert meta.source == "https://www.sohu.com/a/992035075_121284943"
        assert meta.author == "极目新闻"

    def test_to_dict(self):
        """確認 to_dict 回傳正確結構。"""
        meta = parse_raw_metadata(FIXTURE_CONTENT)
        d = meta.to_dict()
        assert set(d.keys()) == {"date", "source", "author"}

    def test_missing_source_returns_none(self):
        """缺少【原文來源】應回傳 None。"""
        broken = FIXTURE_CONTENT.replace("【原文來源】", "【XXX】")
        assert parse_raw_metadata(broken) is None


# ---------------------------------------------------------------------------
# parse_raw_content
# ---------------------------------------------------------------------------


class TestParseRawContent:
    """測試 raw 內容解析（標題 / 正文 / identifier）。"""

    def test_title_extracted(self):
        """確認標題正確抽取。"""
        parsed = parse_raw_content(FIXTURE_CONTENT, FIXTURE_FILENAME)
        assert parsed["title"] == "恶意欠薪84755元，一服饰厂老板逃匿外地被警方抓获"

    def test_body_not_empty(self):
        """正文不應為空。"""
        parsed = parse_raw_content(FIXTURE_CONTENT, FIXTURE_FILENAME)
        assert len(parsed["body"]) > 100

    def test_identifier_from_filename(self):
        """identifier 應從檔名數字前綴生成。"""
        parsed = parse_raw_content(FIXTURE_CONTENT, FIXTURE_FILENAME)
        assert parsed["identifier"] == "NEWS-0005"


# ---------------------------------------------------------------------------
# prompt 組裝
# ---------------------------------------------------------------------------


class TestPrompts:
    """測試 prompt 模組。"""

    def test_system_prompt_loaded(self):
        """SYSTEM_PROMPT 應成功從 schema markdown 載入。"""
        assert len(SYSTEM_PROMPT) > 100
        assert "JSON" in SYSTEM_PROMPT

    def test_user_prompt_contains_title_and_body(self):
        """user prompt 應包含傳入的標題和正文。"""
        prompt = build_user_prompt(title="測試標題", body="測試正文內容")
        assert "測試標題" in prompt
        assert "測試正文內容" in prompt


# ---------------------------------------------------------------------------
# _strip_json_comments
# ---------------------------------------------------------------------------


class TestStripJsonComments:
    """測試 JSON 註解清理。"""

    def test_removes_line_comment(self):
        """移除行尾 // 註解。"""
        raw = '{"key": "value"} // this is a comment'
        result = _strip_json_comments(raw)
        assert "//" not in result
        assert json.loads(result) == {"key": "value"}

    def test_preserves_url_in_string(self):
        """字串值中的 // 不應被移除。"""
        raw = '{"url": "https://example.com"}'
        result = _strip_json_comments(raw)
        assert json.loads(result) == {"url": "https://example.com"}

    def test_removes_trailing_comma(self):
        """移除 JSON 不允許的尾隨逗號。"""
        raw = '{"a": 1, "b": 2,}'
        result = _strip_json_comments(raw)
        assert json.loads(result) == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# merge_result
# ---------------------------------------------------------------------------


class TestMergeResult:
    """測試 LLM 結果與 metadata 合併。"""

    def test_structure(self):
        """合併結果應包含 metadata / 5W1H / themes / events。"""
        llm = {
            "5W1H": {"who": "A", "what": "B"},
            "themes": ["工資"],
            "events": [{"date": {}}],
        }
        meta = {"date": "2026-01-01", "source": "src", "author": "auth"}
        parsed = {"title": "T", "body": "B", "identifier": "NEWS-0001"}
        result = merge_result(llm, meta, parsed)
        assert set(result.keys()) == {"metadata", "5W1H", "themes", "events"}
        assert result["metadata"]["title"] == "T"
        assert result["metadata"]["identifier"] == "NEWS-0001"


# ---------------------------------------------------------------------------
# extract_single (dry-run, 不調用 LLM)
# ---------------------------------------------------------------------------


class TestExtractSingleDryRun:
    """測試 extract_single dry-run 模式。"""

    def test_dry_run_succeeds(self, tmp_path):
        """dry-run 應回傳 True 且不寫出檔案。"""
        sample = tmp_path / FIXTURE_FILENAME
        sample.write_text(FIXTURE_CONTENT, encoding="utf-8")
        result = extract_single(sample, dry_run=True)
        assert result is True

    def test_missing_body_returns_false(self, tmp_path):
        """正文為空時應回傳 False。"""
        no_body = FIXTURE_CONTENT.split("【內文】")[0] + "【內文】\n"
        sample = tmp_path / FIXTURE_FILENAME
        sample.write_text(no_body, encoding="utf-8")
        result = extract_single(sample, dry_run=True)
        assert result is False


# ---------------------------------------------------------------------------
# extract_single (mock LLM, 驗證完整寫檔流程)
# ---------------------------------------------------------------------------


class TestExtractSingleWithMockLLM:
    """Mock LLM 驗證完整 pipeline 輸出。"""

    FAKE_LLM_RESPONSE = {
        "5W1H": {
            "who": "董某某與15名被欠薪職工",
            "what": "恶意拖欠工资84755元",
            "when": "2025年4月至2026年2月",
            "where": "湖北省武穴市",
            "why": "以资金周转困难为由",
            "how": "职工投诉后警方远赴杭州抓获",
        },
        "themes": ["工資、報酬與最低工資"],
        "events": [{"date": {"event_date_start": "2025-04-01"}}],
    }

    def test_full_pipeline_writes_json(self, tmp_path, monkeypatch):
        """mock call_llm 後，extract_single 應寫出合法 JSON。"""
        sample = tmp_path / FIXTURE_FILENAME
        sample.write_text(FIXTURE_CONTENT, encoding="utf-8")

        monkeypatch.setattr(
            "scripts.extract_schema.call_llm",
            lambda *_a, **_kw: self.FAKE_LLM_RESPONSE,
        )
        import scripts.extract_schema as mod

        original_out = mod.OUT_DIR
        monkeypatch.setattr(mod, "OUT_DIR", tmp_path / "out")

        result = extract_single(sample, dry_run=False)
        assert result is True

        out_file = tmp_path / "out" / (sample.stem + ".json")
        assert out_file.exists()

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["metadata"]["title"] == "恶意欠薪84755元，一服饰厂老板逃匿外地被警方抓获"
        assert data["metadata"]["date"] == "2026-03-03"
        assert "5W1H" in data
        assert len(data["themes"]) > 0

        monkeypatch.setattr(mod, "OUT_DIR", original_out)
