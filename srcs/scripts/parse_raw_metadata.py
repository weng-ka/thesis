#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ENV: Thesis
"""
從 raw 勞工新聞文本中解析元數據（date、source、author）。

僅抽取源站提供的三項欄位，其餘由 LLM 負責。
author 若源站為空則回傳 "不明"。
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RawMetadata:
    """從 raw txt 解析出的元數據（date、source、author）。"""

    date: str
    source: str
    author: str

    def to_dict(self) -> dict[str, str]:
        """轉為 metadata 子結構。"""
        return {
            "date": self.date,
            "source": self.source,
            "author": self.author,
        }


# 數據區塊中，緊接在 作者： 之後的「下一欄位」關鍵字，若下一行是這些則表示 author 為空
_NEXT_KEY_AFTER_AUTHOR = re.compile(
    r"^(主题分类|內容類型|关键词|涉及行业|涉及职业|地点|相关议题)[：:]?\s*$"
)


def _extract_field_after_key(text: str, key: str) -> str | None:
    """
    從文本中抽取「Key：\\nValue」格式的 Value。
    若 Value 行為空或為下一個 Key 行，則回傳 None。
    """
    pattern = rf"{re.escape(key)}[：:]?\s*\n\s*(.+?)(?=\n|$)"
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not m:
        return None
    val = m.group(1).strip()
    if not val:
        return None
    # 若該行本身是下一個 Key（含：），則視為空
    if "：" in val or ":" in val:
        first_line = val.split("\n")[0].strip()
        if _NEXT_KEY_AFTER_AUTHOR.match(first_line) or first_line.endswith("："):
            return None
    return val


def parse_raw_metadata(content: str) -> RawMetadata | None:
    """
    從 raw 新聞文本內容解析 date、source、author。

    Args:
        content: 完整 raw txt 內容。

    Returns:
        RawMetadata 或 None（解析失敗時）。
    """
    # 1. source：【原文來源】與【數據】之間的內容
    source_match = re.search(
        r"【原文來源】\s*\n\s*(.+?)\s*\n\s*【數據】",
        content,
        re.DOTALL,
    )
    source = source_match.group(1).strip() if source_match else ""
    if not source:
        return None

    # 2. date：發布日期
    date_val = _extract_field_after_key(content, "发布日期")
    if not date_val:
        return None
    # 正規化為 YYYY-MM-DD
    date_clean = re.sub(r"\s+", "", date_val)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_clean):
        # 嘗試解析其他格式，例如 2022/07/05
        alt = re.search(r"(\d{4})[/\-]?(\d{1,2})[/\-]?(\d{1,2})", date_clean)
        if alt:
            y, m, d = alt.group(1), alt.group(2).zfill(2), alt.group(3).zfill(2)
            date_clean = f"{y}-{m}-{d}"
        else:
            return None

    # 3. author：作者，空則 "NA"
    author_val = _extract_field_after_key(content, "作者")
    if not author_val:
        author_val = "NA"
    else:
        # 若該行是下一個 Key（如 主题分类：），則 author 為空
        if _NEXT_KEY_AFTER_AUTHOR.match(author_val.split("\n")[0].strip()):
            author_val = "NA"
        else:
            author_val = author_val.split("\n")[0].strip() or "NA"

    return RawMetadata(date=date_clean, source=source, author=author_val)


def parse_raw_file(path: str | Path) -> RawMetadata | None:
    """
    從 raw txt 檔案路徑解析元數據。

    Args:
        path: raw txt 檔案路徑。

    Returns:
        RawMetadata 或 None。
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        return parse_raw_metadata(text)
    except Exception:
        return None


def main() -> None:
    """CLI：對單一檔案或目錄進行解析測試。"""
    import argparse

    parser = argparse.ArgumentParser(description="解析 raw 新聞元數據（date、source、author）")
    parser.add_argument("path", help="raw txt 檔案或目錄路徑")
    parser.add_argument("-n", "--limit", type=int, default=5, help="目錄模式下最多顯示幾筆（預設 5）")
    args = parser.parse_args()

    p = Path(args.path)
    if p.is_file():
        meta = parse_raw_file(p)
        if meta:
            print(meta.to_dict())
        else:
            print("解析失敗")
    elif p.is_dir():
        files = sorted(p.glob("*.txt"))[: args.limit]
        for f in files:
            meta = parse_raw_file(f)
            status = meta.to_dict() if meta else "FAIL"
            print(f"{f.name}: {status}")
    else:
        print("路徑不存在")


if __name__ == "__main__":
    main()
