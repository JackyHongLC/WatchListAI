import csv
import base64
import io
import json
import mimetypes
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import streamlit as st

try:
    from openai import OpenAI
except ImportError:  # The app still works in rule-based mode.
    OpenAI = None

try:
    from google import genai
except ImportError:  # Gemini support is optional.
    genai = None


STATUS_OPTIONS = ["未看", "觀看中", "已看", "暫停", "棄追", "想重看"]
PLATFORM_PATTERNS = {
    "YouTube": ["youtube.com", "youtu.be"],
    "Netflix": ["netflix.com"],
    "動畫瘋": ["ani.gamer.com.tw", "gamer.com.tw"],
    "Bilibili": ["bilibili.com", "b23.tv"],
    "Disney+": ["disneyplus.com"],
    "Coursera": ["coursera.org"],
    "Udemy": ["udemy.com"],
    "edX": ["edx.org"],
}
APP_DIR = Path(__file__).parent
ASSET_DIR = APP_DIR / "assets"
BACKGROUND_CANDIDATES = ["background.jpg", "background.jpeg", "background.png", "background.webp"]
MUSIC_CANDIDATES = ["bgm.mp3", "bgm.wav", "bgm.ogg", "music.mp3"]


@dataclass
class WatchItem:
    platform: str
    series: str
    season: Optional[int]
    episode: Optional[int]
    title: str
    url: str
    category: str
    status: str
    note: str
    source_line: str
    inferred: bool = False


def detect_url(text: str) -> str:
    match = re.search(r"https?://\S+", text)
    return match.group(0).rstrip("),.;") if match else ""


def find_first_asset(candidates: List[str]) -> Optional[Path]:
    for filename in candidates:
        path = ASSET_DIR / filename
        if path.exists():
            return path
    return None


def apply_background_image() -> None:
    background = find_first_asset(BACKGROUND_CANDIDATES)
    if not background:
        return

    mime_type = mimetypes.guess_type(background.name)[0] or "image/jpeg"
    encoded = base64.b64encode(background.read_bytes()).decode("utf-8")
    st.markdown(
        f"""
        <style>
        .stApp {{
            background:
                linear-gradient(rgba(255, 255, 255, 0.90), rgba(255, 255, 255, 0.90)),
                url("data:{mime_type};base64,{encoded}");
            background-size: cover;
            background-position: center;
            background-attachment: fixed;
        }}
        [data-testid="stSidebar"] {{
            background-color: rgba(255, 255, 255, 0.92);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def show_background_music() -> None:
    music = find_first_asset(MUSIC_CANDIDATES)
    if music:
        st.sidebar.audio(str(music))
        st.sidebar.caption(f"背景音樂：{music.name}")
    else:
        st.sidebar.caption("可放入 assets/bgm.mp3 作為背景音樂。")


def detect_platform(text: str, url: str) -> str:
    haystack = f"{text} {url}".lower()
    for platform, patterns in PLATFORM_PATTERNS.items():
        if any(pattern in haystack for pattern in patterns):
            return platform

    explicit = {
        "yt": "YouTube",
        "youtube": "YouTube",
        "netflix": "Netflix",
        "動畫瘋": "動畫瘋",
        "巴哈": "動畫瘋",
        "bilibili": "Bilibili",
        "b站": "Bilibili",
        "disney": "Disney+",
        "coursera": "Coursera",
        "udemy": "Udemy",
        "edx": "edX",
    }
    for key, value in explicit.items():
        if key in haystack:
            return value
    return "自訂"


def detect_season_episode(text: str) -> Tuple[Optional[int], Optional[int]]:
    patterns = [
        r"S(?P<season>\d{1,2})\s*E(?P<episode>\d{1,3})",
        r"S(?P<season>\d{1,2})\s*EP(?P<episode>\d{1,3})",
        r"第\s*(?P<season>\d{1,2})\s*季\s*第\s*(?P<episode>\d{1,3})\s*[集話]",
        r"(?P<season>\d{1,2})\s*季\s*(?P<episode>\d{1,3})\s*[集話]",
        r"EP\s*(?P<episode>\d{1,3})",
        r"E(?P<episode>\d{1,3})",
        r"第\s*(?P<episode>\d{1,3})\s*[集話]",
    ]
    normalized = text.upper()
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            season = match.groupdict().get("season")
            episode = match.groupdict().get("episode")
            return int(season) if season else 1, int(episode) if episode else None

    loose_numbers = re.findall(r"(?<!\d)(\d{1,3})(?!\d)", text)
    if loose_numbers:
        return 1, int(loose_numbers[-1])
    return None, None


def clean_title_parts(text: str, url: str) -> str:
    cleaned = text.replace(url, "")
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"\b(YT|YouTube|Netflix|Bilibili|Disney\+|Coursera|Udemy|edX)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(動畫瘋|巴哈|B站)", "", cleaned)
    cleaned = re.sub(r"S\d{1,2}\s*E(P)?\d{1,3}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"EP\s*\d{1,3}|E\d{1,3}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"第\s*\d+\s*[季集話]", "", cleaned)
    cleaned = re.sub(r"\d+\s*季|\d+\s*[集話]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_:|,，")
    return cleaned


def guess_category(text: str) -> str:
    lowered = text.lower()
    if any(word in lowered for word in ["python", "machine learning", "deep learning", "transformer", "course", "lecture", "教學", "課程"]):
        return "課程"
    if any(word in text for word in ["動畫", "動漫", "番", "集", "話", "葬送", "咒術", "鬼滅"]):
        return "動畫"
    if any(word in lowered for word in ["netflix", "season", "s0", "drama"]):
        return "影集"
    return "未分類"


def split_series_and_title(cleaned: str, episode: Optional[int]) -> Tuple[str, str]:
    if not cleaned:
        return "未命名系列", ""

    separators = [" - ", "：", ":", "|", "｜"]
    for sep in separators:
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            return left.strip() or "未命名系列", right.strip()

    parts = cleaned.split()
    if len(parts) <= 2:
        return cleaned, ""
    if episode is not None:
        return " ".join(parts[:-1]), parts[-1]
    return cleaned, ""


def parse_rule_based(raw_text: str) -> List[WatchItem]:
    items = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        url = detect_url(line)
        platform = detect_platform(line, url)
        season, episode = detect_season_episode(line)
        cleaned = clean_title_parts(line, url)
        series, title = split_series_and_title(cleaned, episode)
        items.append(
            WatchItem(
                platform=platform,
                series=series,
                season=season,
                episode=episode,
                title=title,
                url=url,
                category=guess_category(line),
                status="未看",
                note="",
                source_line=line,
                inferred=True,
            )
        )
    return items


AI_PARSE_PROMPT = """
你是跨平台播放清單整理助理。請根據使用者提供的每一行資料解析影片清單。
重點限制：
- 不要假裝你能觀看影片內容。
- 以使用者提供的片名、季數、集數、平台、連結為主。
- 若資訊是推測的，inferred 設為 true。
- season 與 episode 若無法判斷，填 null。
- status 預設為「未看」。
- category 可用：課程、動畫、影集、電影、紀錄片、直播回放、未分類。

只輸出 JSON array，每個物件包含：
platform, series, season, episode, title, url, category, status, note, source_line, inferred
"""


def extract_json_array(content: str) -> List[Dict]:
    text = content.strip()
    text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError("AI 回傳內容不是 JSON array")
    return json.loads(text[start : end + 1])


def rows_to_watch_items(data: List[Dict]) -> List[WatchItem]:
    return [
        WatchItem(
            platform=row.get("platform") or "自訂",
            series=row.get("series") or "未命名系列",
            season=row.get("season"),
            episode=row.get("episode"),
            title=row.get("title") or "",
            url=row.get("url") or "",
            category=row.get("category") or "未分類",
            status=row.get("status") or "未看",
            note=row.get("note") or "",
            source_line=row.get("source_line") or "",
            inferred=bool(row.get("inferred", True)),
        )
        for row in data
    ]


def parse_with_openai(raw_text: str, api_key: str, model: str) -> List[WatchItem]:
    if OpenAI is None:
        raise RuntimeError("尚未安裝 openai 套件，請先執行 pip install -r requirements.txt")

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": AI_PARSE_PROMPT},
            {"role": "user", "content": raw_text},
        ],
        temperature=0.2,
    )
    content = response.choices[0].message.content or "[]"
    return rows_to_watch_items(extract_json_array(content))


def parse_with_gemini(raw_text: str, api_key: str, model: str) -> List[WatchItem]:
    if genai is None:
        raise RuntimeError("尚未安裝 google-genai 套件，請先執行 pip install -r requirements.txt")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=f"{AI_PARSE_PROMPT}\n\n使用者資料：\n{raw_text}",
    )
    content = getattr(response, "text", "") or "[]"
    return rows_to_watch_items(extract_json_array(content))


def parse_with_ai(raw_text: str, api_key: str, provider: str, model: str) -> List[WatchItem]:
    if provider == "Gemini":
        return parse_with_gemini(raw_text, api_key, model)
    return parse_with_openai(raw_text, api_key, model)


def normalize_items(items: List[WatchItem]) -> List[Dict]:
    rows = [asdict(item) for item in items]
    return sorted(
        rows,
        key=lambda row: (
            row["series"].lower(),
            row["season"] if row["season"] is not None else 999,
            row["episode"] if row["episode"] is not None else 9999,
            row["title"].lower(),
        ),
    )


def find_duplicates(rows: List[Dict]) -> List[str]:
    seen = {}
    duplicates = []
    for row in rows:
        keys = []
        if row["url"]:
            keys.append(("連結", row["url"]))
        if row["episode"] is not None:
            keys.append(("作品集數", f"{row['series']}|{row['season']}|{row['episode']}"))
        for label, key in keys:
            if key in seen:
                duplicates.append(f"{label}重複：{row['series']} S{row['season'] or 1:02d}E{row['episode'] or 0:02d}")
            seen[key] = True
    return duplicates


def find_missing_episodes(rows: List[Dict]) -> List[str]:
    grouped: Dict[Tuple[str, int], List[int]] = {}
    for row in rows:
        if row["episode"] is None:
            continue
        key = (row["series"], row["season"] or 1)
        grouped.setdefault(key, []).append(int(row["episode"]))

    messages = []
    for (series, season), episodes in grouped.items():
        unique = sorted(set(episodes))
        if len(unique) < 2:
            continue
        missing = [ep for ep in range(unique[0], unique[-1] + 1) if ep not in unique]
        if missing:
            formatted = ", ".join(f"EP{ep:02d}" for ep in missing)
            messages.append(f"{series} S{season:02d} 可能缺少：{formatted}")
    return messages


def completion_summary(rows: List[Dict]) -> List[str]:
    grouped: Dict[str, Dict[str, int]] = {}
    for row in rows:
        bucket = grouped.setdefault(row["series"], {"total": 0, "done": 0})
        bucket["total"] += 1
        if row["status"] == "已看":
            bucket["done"] += 1

    summaries = []
    for series, counts in grouped.items():
        rate = counts["done"] / counts["total"] * 100 if counts["total"] else 0
        summaries.append(f"{series}: {counts['done']} / {counts['total']} 已看，完成率 {rate:.1f}%")
    return summaries


def generate_markdown(rows: List[Dict]) -> str:
    lines = ["# WatchList AI 整理清單", ""]
    current_series = None
    for row in rows:
        if row["series"] != current_series:
            current_series = row["series"]
            lines.extend(["", f"## {current_series}", ""])
            lines.append("| 集數 | 標題 | 平台 | 分類 | 狀態 | 連結 |")
            lines.append("|---|---|---|---|---|---|")
        episode = f"S{row['season'] or 1:02d}E{row['episode']:02d}" if row["episode"] is not None else "-"
        title = row["title"] or "-"
        link = row["url"] or "-"
        lines.append(f"| {episode} | {title} | {row['platform']} | {row['category']} | {row['status']} | {link} |")
    return "\n".join(lines).strip() + "\n"


def rows_to_csv(rows: List[Dict]) -> str:
    output = io.StringIO()
    fieldnames = ["platform", "series", "season", "episode", "title", "url", "category", "status", "note", "inferred"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return output.getvalue()


def make_rule_based_plan(rows: List[Dict], per_day: int, days: int) -> str:
    unwatched = [row for row in rows if row["status"] != "已看"]
    lines = ["# 本週觀看計畫", ""]
    index = 0
    for day in range(1, days + 1):
        lines.append(f"## Day {day}")
        picks = unwatched[index : index + per_day]
        index += per_day
        if not picks:
            lines.append("- 休息或複習已看內容")
            continue
        for row in picks:
            episode = f"S{row['season'] or 1:02d}E{row['episode']:02d}" if row["episode"] is not None else "未標集數"
            title = f" - {row['title']}" if row["title"] else ""
            lines.append(f"- {row['series']} {episode}{title}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    st.set_page_config(page_title="WatchList AI", page_icon="▶", layout="wide")
    apply_background_image()
    st.title("WatchList AI")
    st.caption("跨平台智慧播放清單與觀看進度整理工具")

    with st.sidebar:
        st.header("設定")
        use_ai = st.toggle("啟用 AI 解析", value=False)
        provider = st.selectbox("AI 供應商", ["OpenAI", "Gemini"], disabled=not use_ai)
        model_options = {
            "OpenAI": ["gpt-4.1-mini", "gpt-4o-mini"],
            "Gemini": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash"],
        }
        api_key_label = f"{provider} API Key"
        api_key = st.text_input(api_key_label, type="password", disabled=not use_ai)
        model = st.selectbox("模型", model_options[provider], disabled=not use_ai)
        st.divider()
        show_background_music()
        st.divider()
        st.write("AI 無法保證能讀取 Netflix、動畫瘋等平台內容。本工具以你提供的片名、集數與備註為主要依據。")

    sample = """https://youtube.com/watch?v=abc Python Machine Learning EP1 Introduction
Netflix 黑鏡 S6E2 Loch Henry
動畫瘋 葬送的芙莉蓮 第03話 殺人的魔法
Bilibili Transformer Course EP10 Attention
Python Machine Learning EP3 Model Training"""

    raw_text = st.text_area(
        "貼上影片資料",
        value=sample,
        height=180,
        help="每行一筆資料，可包含平台、連結、片名、季數、集數、備註。",
    )

    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        parse_clicked = st.button("整理播放清單", type="primary", use_container_width=True)
    with col_b:
        clear_clicked = st.button("清空結果", use_container_width=True)

    if clear_clicked:
        st.session_state.pop("rows", None)

    if parse_clicked:
        try:
            if use_ai:
                if not api_key:
                    st.warning("啟用 AI 解析時需要輸入 API Key。已改用基本規則解析。")
                    items = parse_rule_based(raw_text)
                else:
                    items = parse_with_ai(raw_text, api_key, provider, model)
            else:
                items = parse_rule_based(raw_text)
            st.session_state.rows = normalize_items(items)
        except Exception as exc:
            st.error(f"解析失敗：{exc}")
            st.info("已改用基本規則解析。")
            st.session_state.rows = normalize_items(parse_rule_based(raw_text))

    rows = st.session_state.get("rows", [])
    if not rows:
        st.info("貼上清單後點選「整理播放清單」開始。")
        return

    st.subheader("整理結果")
    edited_rows = st.data_editor(
        rows,
        column_config={
            "status": st.column_config.SelectboxColumn("status", options=STATUS_OPTIONS),
            "url": st.column_config.LinkColumn("url"),
            "inferred": st.column_config.CheckboxColumn("inferred"),
        },
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
    )
    st.session_state.rows = edited_rows

    missing = find_missing_episodes(edited_rows)
    duplicates = find_duplicates(edited_rows)
    summaries = completion_summary(edited_rows)

    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("總項目", len(edited_rows))
    metric_b.metric("可能缺集", len(missing))
    metric_c.metric("重複提醒", len(duplicates))

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("檢查提醒")
        if not missing and not duplicates:
            st.success("目前沒有發現缺集或重複項目。")
        for message in missing:
            st.warning(message)
        for message in duplicates:
            st.warning(message)

    with col2:
        st.subheader("觀看進度")
        for summary in summaries:
            st.write(summary)

    st.subheader("觀看計畫")
    plan_col1, plan_col2 = st.columns(2)
    with plan_col1:
        per_day = st.number_input("每天安排幾集", min_value=1, max_value=10, value=2)
    with plan_col2:
        days = st.number_input("安排幾天", min_value=1, max_value=14, value=7)
    plan = make_rule_based_plan(edited_rows, int(per_day), int(days))
    st.markdown(plan)

    st.subheader("匯出")
    markdown = generate_markdown(edited_rows)
    csv_text = rows_to_csv(edited_rows)
    json_text = json.dumps(edited_rows, ensure_ascii=False, indent=2)
    dl1, dl2, dl3 = st.columns(3)
    dl1.download_button("下載 Markdown", markdown, file_name="watchlist.md", mime="text/markdown", use_container_width=True)
    dl2.download_button("下載 CSV", csv_text, file_name="watchlist.csv", mime="text/csv", use_container_width=True)
    dl3.download_button("下載 JSON", json_text, file_name="watchlist.json", mime="application/json", use_container_width=True)


if __name__ == "__main__":
    main()
