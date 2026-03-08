"""
法律條文解析腳本。

將 data/law_corpus/raw/ 中的法律原始文本按「條」切分，
輸出結構化 JSON 至 data/law_corpus/segmented/。

切分策略：
  1. 先整行移除章/節/編標題
  2. 以「行首出現的條號」為切分邊界（忽略正文內的法條引用）
  3. 對每條法條提取款號（如有）
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from config.paths import LAW_RAW_DIR, LAW_SEGMENTED_DIR

RAW_DIR = LAW_RAW_DIR
OUTPUT_DIR = LAW_SEGMENTED_DIR
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADING_LINE_RE = re.compile(
    r"^[\s\u3000\u2002]*(第[一二三四五六七八九十百零〇]+[章节節编編]).+$",
    re.MULTILINE,
)

ARTICLE_START_RE = re.compile(
    r"^[\s\u3000\u2002]*(第[一二三四五六七八九十百零〇]+条)",
    re.MULTILINE,
)

CLAUSE_RE = re.compile(r"（[一二三四五六七八九十]+）")

BOILERPLATE_RE = re.compile(
    r"^本[法条條例办辦法规規定解释釋则則].*?(施行|负责解释|負責解釋)",
    re.DOTALL,
)


def _remove_heading_lines(text: str) -> str:
    """移除所有章/節/編標題行。"""
    return HEADING_LINE_RE.sub("", text)


def _parse_articles(text: str) -> list[dict]:
    """
    以行首條號為邊界切分法條。

    Returns:
        [{"article_number": "第X条", "text": "...", "clauses": [...]}]
    """
    matches = list(ARTICLE_START_RE.finditer(text))
    if not matches:
        return []

    articles: list[dict] = []

    for i, m in enumerate(matches):
        article_number = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()

        content = re.sub(r"^[\s\u3000\u2002]+", "", content)

        clause_markers = CLAUSE_RE.findall(content)
        clauses: list[str] = []
        if clause_markers:
            clause_splits = CLAUSE_RE.split(content)
            for part in clause_splits[1:]:
                stripped = part.strip()
                if stripped:
                    clauses.append(stripped)

        articles.append({
            "article_number": article_number,
            "text": content,
            "clauses": clauses,
        })

    return articles


def parse_law_file(law_path: Path) -> list[dict] | None:
    """
    解析單部法律文本。

    Args:
        law_path: raw txt 檔案路徑。

    Returns:
        結構化法條列表，或 None（檔名格式不符）。
    """
    filename = law_path.stem
    parts = filename.split("_")

    if len(parts) < 3:
        print(f"跳過無法識別的檔名：{law_path.name}")
        return None

    law_id = f"{parts[0]}_{parts[1]}"
    law_name = "_".join(parts[2:])

    text = law_path.read_text(encoding="utf-8")
    text = _remove_heading_lines(text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    raw_articles = _parse_articles(text)

    articles: list[dict] = []
    idx = 0
    for art in raw_articles:
        if BOILERPLATE_RE.match(art["text"]):
            continue
        idx += 1
        articles.append({
            "law_id": law_id,
            "law_name": law_name,
            "article_number": art["article_number"],
            "article_index": idx,
            "text": art["text"],
            "clauses": art["clauses"],
        })

    return articles


def main() -> None:
    """解析所有法律文本並輸出 JSON。"""
    all_paths = sorted(RAW_DIR.glob("law_*.txt"))
    total_articles = 0

    for law_path in all_paths:
        articles = parse_law_file(law_path)
        if articles is None:
            continue

        output_path = OUTPUT_DIR / f"{law_path.stem}.json"
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)

        total_articles += len(articles)
        print(f"  {articles[0]['law_id']} | {len(articles):3d} 條 | {law_path.stem}")

    print(f"\n全部完成：{len(all_paths)} 部法律，共 {total_articles} 條法條")


if __name__ == "__main__":
    main()
