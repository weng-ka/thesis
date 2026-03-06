#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
結構化抽取 Prompt 定義。

SYSTEM_PROMPT 在 runtime 從 schema markdown 動態生成，
修改 schema 即自動生效，無需手動同步。
"""

from pathlib import Path

_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "schema" / "news_structured_schema.md"
)

_ROLE_PREAMBLE = """\
你是一名专业的劳工新闻结构化信息抽取助手。你的任务是阅读一篇中国劳工新闻的标题与正文，按照下方 JSON Schema 抽取结构化特征，输出严格合法的 JSON。

## 总体要求

1. 仅基于新闻文本中明确陈述或可直接推理的信息进行抽取，不得编造或臆测。
2. 所有标注"不可为空"的字段必须填写；标注"可为空"的字段若文本未提及则留空字符串 "" 或空数组 []。
3. 所有 enum 字段必须严格使用下方给定的可选值原文，不得自行改写或新增。
4. 输出仅包含一个 JSON 对象，不包含任何注释、解释或 markdown 标记。
5. metadata 已由程序预填，你无需抽取 metadata，仅抽取 5W1H、themes、events。
6. 5W1H 每个字段必须为 1–2 个包含主语和动词的完整语句，能独立阅读理解，不得使用片段式列举。

---

"""


def _load_schema() -> str:
    """從 schema markdown 讀取完整內容。"""
    return _SCHEMA_PATH.read_text(encoding="utf-8")


def _build_system_prompt() -> str:
    """組合 role preamble + schema 為完整 system prompt。"""
    return _ROLE_PREAMBLE + _load_schema()


SYSTEM_PROMPT: str = _build_system_prompt()


def build_user_prompt(title: str, body: str) -> str:
    """
    構建 user prompt。

    Args:
        title: 新聞標題。
        body: 新聞正文。

    Returns:
        完整 user prompt 字串。
    """
    return f"""\
请对以下劳工新闻进行结构化特征抽取，严格按照 system prompt 中的 JSON Schema 输出。

【标题】
{title}

【正文】
{body}"""
