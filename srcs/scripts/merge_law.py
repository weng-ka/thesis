import os
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "srcs"))

from config.paths import LAW_SEGMENTED_DIR

folder_path = str(LAW_SEGMENTED_DIR)

# 列出當前資料夾所有檔案
all_files = os.listdir(folder_path)

# 篩選出以 law_ 開頭，且以 .json 結尾的檔案
json_files = [f for f in all_files if f.startswith("law_") and f.endswith(".json")]
json_files.sort()  # 字典序排序
print(f"找到 {len(json_files)} 個符合條件的 JSON 檔案。")

all_data = []

for file_name in json_files:
    file_path = os.path.join(folder_path, file_name)
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        all_data.append(data)

# 輸出合併的 JSON
output_file = os.path.join(folder_path, "merged_laws.json")
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(all_data, f, ensure_ascii=False, indent=4)

print(f"合併完成，共 {len(all_data)} 個文件，輸出到 {output_file}")