#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ENV: Thesis

import argparse
import os
import re
import time
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup


# 固定輸出資料夾
OUTDIR = "out_txt"

# 固定抓取頁數：p=0 ... p=200
MAX_P = 200

# 基本網路參數（不在 CLI 暴露）
TIMEOUT = 20
SLEEP_SEC = 0.3
USER_AGENT = "Mozilla/5.0 (ArticleDownloader/2.1)"

# 搜索結果卡片：只用「關鍵 class」匹配（避免 rounded-lg / shadow-md 等字形誤差）
RESULT_CARD_KEY_CLASSES = [
    "max-w-4xl", "p-6", "mb-4", "bg-white", "border", "border-gray-200"
]

# 卡片內目標 flex
RESULT_FLEX_KEY_CLASSES = [
    "flex", "items-center", "justify-between", "overflow-hidden"
]

# 文章頁主容器
ARTICLE_CONTAINER_CLASSES = [
    "container", "max-w-4xl", "mx-auto", "px-8", "py-8", "bg-white",
    "border", "border-gray-200", "rounded-lg"
]


def has_all_classes(tag, classes):
    if not tag or not tag.has_attr("class"):
        return False
    tag_classes = set(tag.get("class", []))
    return all(c in tag_classes for c in classes)


def normalize_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\r\n?", "\n", s)
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def one_line(s: str) -> str:
    s = normalize_text(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = name or ""
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        name = "untitled"
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name


def build_paged_url(list_url: str, p_value: int) -> str:
    """
    把 list_url 的 query 參數 p 設為指定值。
    """
    u = urlparse(list_url)
    q = parse_qs(u.query, keep_blank_values=True)
    q["p"] = [str(p_value)]
    new_query = urlencode(q, doseq=True)
    return urlunparse((u.scheme, u.netloc, u.path, u.params, new_query, u.fragment))


def extract_article_links(list_html: str, limit: int = 20):
    """
    僅從「結果卡片」中抽取文章連結：
    card div (max-w-4xl p-6 mb-4 bg-white border border-gray-200 ...)
        -> flex div (flex items-center justify-between overflow-hidden)
            -> a[href^="/articles/"]
    """
    soup = BeautifulSoup(list_html, "html.parser")

    def is_result_card(tag):
        return tag.name == "div" and has_all_classes(tag, RESULT_CARD_KEY_CLASSES)

    def is_target_flex(tag):
        return tag.name == "div" and has_all_classes(tag, RESULT_FLEX_KEY_CLASSES)

    links = []
    cards = soup.find_all(is_result_card)

    for card in cards:
        for flex in card.find_all(is_target_flex):
            a = flex.find("a", href=True)
            if not a:
                continue
            href = a["href"].strip()
            if href.startswith("/articles/"):
                links.append(href)

    # 去除卡片內的意外重複（保序），並限制每頁最多 20
    # （注意：這不是「全局去重」，只是在同一頁/同一抓取結果內避免同一 href 重複出現）
    seen = set()
    dedup = []
    for h in links:
        if h not in seen:
            seen.add(h)
            dedup.append(h)
        if len(dedup) >= limit:
            break

    return dedup


def extract_article_fields(article_html: str):
    """
    從文章頁 HTML 抽取：標題、原文來源、數據、內文
    """
    soup = BeautifulSoup(article_html, "html.parser")

    container = soup.find(lambda t: t.name == "div" and has_all_classes(t, ARTICLE_CONTAINER_CLASSES))
    if not container:
        raise ValueError("找不到文章主容器（container max-w-4xl ... rounded-lg）")

    # 標題 h1.text-2xl.font-bold.mb-4（用關鍵 class 判斷）
    h1 = container.find(
        "h1",
        class_=lambda c: c and ("text-2xl" in c) and ("font-bold" in c) and ("mb-4" in c)
    )
    title = one_line(h1.get_text(" ", strip=True)) if h1 else ""

    # 原文來源：容器內第一個 div.mb-4（排除 border-b 和 mb-8）
    # 優先取 <a href> 的網址，否則取0
    source = ""
    for d in container.find_all("div"):
        cls = d.get("class", [])
        if "mb-4" in cls and "border-b" not in cls and "mb-8" not in cls:
            a = d.find("a", href=True)
            if a and a["href"].strip():
                source = a["href"].strip()
            else:
                source = "0"
            break

    # 數據：div.mb-4.text-gray-700.border-b.pb-4
    data_div = container.find(
        "div",
        class_=lambda c: c and all(x in c for x in ["mb-4", "text-gray-700", "border-b", "pb-4"])
    )
    data = normalize_text(data_div.get_text("\n", strip=True)) if data_div else ""

    # 內文：div.mb-8.text-gray-700.text-lg
    body_div = container.find(
        "div",
        class_=lambda c: c and all(x in c for x in ["mb-8", "text-gray-700", "text-lg"])
    )
    body = normalize_text(body_div.get_text("\n", strip=True)) if body_div else ""

    return title, source, data, body


def title_fallback(title: str, body: str, max_chars: int = 35) -> str:
    """
    若沒有 title，使用內文前 max_chars 個字作為 title
    """
    if title and title.strip():
        return one_line(title)

    body_1 = one_line(body)
    if not body_1:
        return "untitled"

    return body_1[:max_chars].rstrip()


def main():
    parser = argparse.ArgumentParser(
        description="從搜索結果頁自動翻頁(p=0..200)，下載約 4000 篇文章並輸出 TXT（不做全局去重）。"
    )
    parser.add_argument(
        "--list-url",
        required=True,
        help="搜索結果頁網址（包含 p=0 的 URL；程式會自動改 p=1..200）"
    )
    parser.add_argument(
        "--dump-links",
        action="store_true",
        help="只收集並輸出全部文章連結到 out_txt/links.txt，不下載文章內容"
    )
    args = parser.parse_args()

    os.makedirs(OUTDIR, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    u0 = urlparse(args.list_url)
    if not (u0.scheme and u0.netloc):
        raise SystemExit("list-url 不是有效的網址（需要包含 https://...）。")

    base_url = f"{u0.scheme}://{u0.netloc}"

    # 注意：不做全局去重（允許重複，照順序全部加入）
    all_links = []

    print(f"開始翻頁抓取文章連結：p=0..{MAX_P}")
    for p in range(0, MAX_P + 1):
        page_url = build_paged_url(args.list_url, p)

        resp = session.get(page_url, timeout=TIMEOUT)
        resp.raise_for_status()

        links = extract_article_links(resp.text, limit=20)
        # 你已確認每頁都有 20 篇；即使因意外解析到 0，也不做特殊處理，直接進下一頁
        for h in links:
            all_links.append(urljoin(base_url, h))

        print(f"[p={p}] 取得 {len(links)} 條（累計 {len(all_links)}）")
        time.sleep(SLEEP_SEC)

    if args.dump_links:
        links_path = os.path.join(OUTDIR, "links.txt")
        with open(links_path, "w", encoding="utf-8") as f:
            for url in all_links:
                f.write(url + "\n")
        print(f"已輸出 {len(all_links)} 條文章連結到：{links_path}")
        return

    print(f"開始下載文章並輸出 TXT：共 {len(all_links)} 篇（檔名含連續編號）")

    for idx, article_url in enumerate(all_links, 1):
        try:
            r = session.get(article_url, timeout=TIMEOUT)
            r.raise_for_status()

            title, source, data, body = extract_article_fields(r.text)
            final_title = title_fallback(title, body, max_chars=35)

            filename = f"{idx:04d}_{sanitize_filename(final_title)}.txt"
            outpath = os.path.join(OUTDIR, filename)

            with open(outpath, "w", encoding="utf-8") as f:
                f.write(
                    f"URL: {article_url}\n\n"
                    f"【標題】\n{final_title}\n\n"
                    f"【原文來源】\n{source}\n\n"
                    f"【數據】\n{data}\n\n"
                    f"【內文】\n{body}\n"
                )

            if idx % 50 == 0 or idx == 1 or idx == len(all_links):
                print(f"[{idx}/{len(all_links)}] OK")

        except Exception as e:
            err_path = os.path.join(OUTDIR, f"{idx:04d}_ERROR.txt")
            with open(err_path, "w", encoding="utf-8") as f:
                f.write(f"URL: {article_url}\n\nERROR: {repr(e)}\n")
            print(f"[{idx}/{len(all_links)}] FAIL -> 已輸出 {err_path}")

        time.sleep(SLEEP_SEC)


if __name__ == "__main__":
    main()