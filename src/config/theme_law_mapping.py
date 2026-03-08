"""
勞工議題 → 勞動法條模塊 路由映射表。

每個議題模塊對應一組法律（以 law_id 標識），用於 RAG 檢索階段的子庫路由。
映射依據：開題報告中的 12 個議題模塊劃分。
"""

import re
import unicodedata

THEME_LAW_MAPPING: dict[str, list[str]] = {
    "勞動合同與勞動關係": ["law_01", "law_02", "law_03"],
    "勞動爭議": ["law_04", "law_05", "law_06", "law_07"],
    "工資、報酬與最低工資": ["law_08", "law_09"],
    "工作時間與加班制度": ["law_10", "law_11", "law_12"],
    "休息休假與帶薪年休假制度": ["law_13", "law_14"],
    "解除勞動合同、裁員、經濟補償與賠償": ["law_15", "law_16"],
    "職業病、醫療期與患病勞動者保護": ["law_17", "law_18", "law_19"],
    "工傷保險與工傷認定": ["law_20", "law_21", "law_22", "law_23"],
    "社會保險與福利制度": ["law_24", "law_25", "law_26"],
    "勞務派遣與非典型用工": ["law_27", "law_28"],
    "女職工與未成年工特殊保護": ["law_29", "law_30", "law_31"],
    "就業促進與勞動保障監察": ["law_32", "law_33"],
}

ALL_THEMES: list[str] = list(THEME_LAW_MAPPING.keys())

ALL_LAW_IDS: set[str] = {
    lid for ids in THEME_LAW_MAPPING.values() for lid in ids
}

_SIMPLIFIED_TO_CANONICAL: dict[str, str] = {
    "劳动合同与劳动关系": "勞動合同與勞動關係",
    "劳动争议": "勞動爭議",
    "工资、报酬与最低工资": "工資、報酬與最低工資",
    "工作时间与加班制度": "工作時間與加班制度",
    "休息休假与带薪年休假制度": "休息休假與帶薪年休假制度",
    "解除劳动合同、裁员、经济补偿与赔偿": "解除勞動合同、裁員、經濟補償與賠償",
    "职业病、医疗期与患病劳动者保护": "職業病、醫療期與患病勞動者保護",
    "工伤保险与工伤认定": "工傷保險與工傷認定",
    "社会保险与福利制度": "社會保險與福利制度",
    "劳务派遣与非典型用工": "勞務派遣與非典型用工",
    "女职工与未成年工特殊保护": "女職工與未成年工特殊保護",
    "就业促进与劳动保障监察": "就業促進與勞動保障監察",
    "勞動保障監察": "就業促進與勞動保障監察",
}


def _strip_invisible(s: str) -> str:
    """移除零寬字元等不可見 Unicode 字元。"""
    return "".join(
        ch for ch in s
        if unicodedata.category(ch)[0] != "C" or ch in "\n\r\t"
    )


def normalize_theme(raw: str) -> str | None:
    """
    將 LLM 輸出的議題名稱正規化為 THEME_LAW_MAPPING 中的標準 key。

    處理：簡體→繁體、零寬字元、多餘空白、部分匹配。
    找不到對應則回傳 None。
    """
    cleaned = _strip_invisible(raw).strip()
    cleaned = re.sub(r"\s+", "", cleaned)

    if cleaned in THEME_LAW_MAPPING:
        return cleaned

    if cleaned in _SIMPLIFIED_TO_CANONICAL:
        return _SIMPLIFIED_TO_CANONICAL[cleaned]

    for canonical in THEME_LAW_MAPPING:
        if cleaned in canonical or canonical in cleaned:
            return canonical

    return None


def get_law_ids_for_themes(themes: list[str]) -> dict[str, list[str]]:
    """
    給定一組議題名稱（可能含簡體/髒數據），回傳正規化後的 {theme: [law_ids]} 映射。
    無法辨識的議題會被跳過並印出警告。
    """
    result: dict[str, list[str]] = {}
    for raw_theme in themes:
        canonical = normalize_theme(raw_theme)
        if canonical is None:
            print(f"[WARN] 無法辨識的議題名稱，已跳過：'{raw_theme}'")
            continue
        if canonical not in result:
            result[canonical] = THEME_LAW_MAPPING[canonical]
    return result
