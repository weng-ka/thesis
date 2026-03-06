import re
import json
from pathlib import Path

# ========= 路径配置 =========
RAW_DIR = Path("raw")
OUTPUT_DIR = Path("segmented")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ========= 正则模式 =========
ARTICLE_PATTERN = re.compile(r"(第[一二三四五六七八九十百零〇]+条)")
CLAUSE_PATTERN = re.compile(r"（[一二三四五六七八九十]+）")
CHAPTER_PATTERN = re.compile(r"^第[一二三四五六七八九十百零〇]+章.*?\n")

# ========= 遍历所有法律文本 =========
for law_path in sorted(RAW_DIR.glob("law_*.txt")):
    filename = law_path.stem
    parts = filename.split("_", 1)

    filename = law_path.stem
    parts = filename.split("_")

    if len(parts) < 3:
        print(f"跳过无法识别的文件名：{law_path.name}")
        continue

    law_id = f"{parts[0]}_{parts[1]}"
    law_name = "_".join(parts[2:])

    print(f"正在处理：{law_id} {law_name}")

    text = law_path.read_text(encoding="utf-8")
    text = re.sub(r"\n+", "\n", text.strip())

    split_parts = ARTICLE_PATTERN.split(text)

    articles = []
    article_index = 1

    for i in range(1, len(split_parts), 2):
        article_number = split_parts[i].strip()
        content = split_parts[i + 1].strip()

        # 去除章标题（若混入）
        content = CHAPTER_PATTERN.sub("", content).strip()

        # 提取款（合并在同一条下）
        clause_splits = CLAUSE_PATTERN.split(content)
        clause_markers = CLAUSE_PATTERN.findall(content)

        clauses = []
        if clause_markers:
            for clause_text in clause_splits[1:]:
                clauses.append(clause_text.strip())

        article_obj = {
            "law_id": law_id,
            "law_name": law_name,
            "article_number": article_number,
            "article_index": article_index,
            "text": content,
            "clauses": clauses
        }

        articles.append(article_obj)
        article_index += 1

    # ========= 输出 JSON（每部法一个文件） =========
    output_path = OUTPUT_DIR / f"{filename}.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

    print(f"✔ 输出 {len(articles)} 条法条 → {output_path.name}")

print("全部法律处理完成。")