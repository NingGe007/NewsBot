# ============================================================
# daily_report.py — 每日早报/晚报（DeepSeek 引擎）
# ============================================================

import json
import sys
import requests
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from openai import OpenAI
from config import DEEPSEEK_API_KEY
from state import load_today_pushed, clear_today_pushed
from feishu import send_daily_report

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

HEADERS = {"User-Agent": "NewsBot/1.0 contact@newsbot.com"}

REPORT_RSS = [
    {"source": "Reuters", "url": "https://news.google.com/rss/search?q=site:reuters.com+finance+OR+markets&hl=en-US&gl=US&ceid=US:en"},
    {"source": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"source": "Bloomberg", "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"source": "WSJ", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
]


def fetch_market_indices() -> str:
    indices = {
        "^GSPC": "S&P 500",
        "^DJI": "道指",
        "^IXIC": "纳指",
    }
    results = []
    for symbol, name in indices.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = resp.json()
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev_close = meta.get("chartPreviousClose", 0)
            if prev_close and price:
                change_pct = ((price - prev_close) / prev_close) * 100
                arrow = "↑" if change_pct >= 0 else "↓"
                results.append(f"{name} {arrow}{abs(change_pct):.2f}%")
        except Exception:
            continue
    return "  |  ".join(results) if results else "指数数据暂时无法获取"


def fetch_market_headlines(hours: int = 14) -> list[str]:
    headlines = []
    seen = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    for feed in REPORT_RSS:
        try:
            resp = requests.get(feed["url"], headers=HEADERS, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")
            count = 0
            for item in items:
                if count >= 10:
                    break
                title_el = item.find("title")
                if title_el is None or not title_el.text:
                    continue
                title = title_el.text.strip()
                if title in seen:
                    continue
                pub_el = item.find("pubDate")
                if pub_el and pub_el.text:
                    try:
                        pub_time = parsedate_to_datetime(pub_el.text)
                        if pub_time < cutoff:
                            continue
                    except Exception:
                        pass
                seen.add(title)
                headlines.append(f"[{feed['source']}] {title}")
                count += 1
        except Exception:
            continue

    return headlines[:40]


REPORT_PROMPT = """你是一位专业投资分析师，覆盖美股、A股、港股三大市场。请生成一份简洁的{report_type}，供个人投资者参考。

要求：
- 语言专业简洁，逻辑清晰
- 重点突出核心驱动因素和风险点
- 用中文撰写，ticker/公司名/专有名词保持英文

数据参考：

三大指数：{indices}

今日已推送的信号：
{pushed_records}

市场头条：
{market_headlines}

今日被过滤的低影响新闻（筛选有潜在价值的列出）：
{filtered_records}

请严格按以下格式输出：

📊 **市场概览**
- 三大指数表现（直接写数据）
- 整体市场情绪：risk-on / risk-off（一句话）
- 核心驱动力（一句话）

---

🔴 **看涨信号**
- $TICKER 或「板块」— 核心逻辑（一句话）
（无则写"暂无"）

🟢 **看跌信号**
- $TICKER 或「板块」— 核心逻辑（一句话）
（无则写"暂无"）

---

📌 **明日关注**
- 需要关注的事件或数据（1-3条）

📋 **低影响池筛选**
- 如有值得关注的列1-3条，无则省略此板块

---

⚠️ 以上内容仅供参考，不构成投资建议。

控制在 500 字以内。"""


def _call_deepseek(prompt: str) -> str:
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1200,
    )
    return response.choices[0].message.content.strip()


def generate_report(report_type: str) -> str:
    print(f"[{report_type}] 抓取指数数据...")
    indices_str = fetch_market_indices()
    print(f"[{report_type}] 指数: {indices_str}")

    records = load_today_pushed()
    pushed_items = []
    filtered_items = []
    for r in records:
        targets = []
        targets.extend([f"${t}" for t in r.get("tickers", [])])
        targets.extend([f"[{s}板块]" for s in r.get("sectors", [])])
        targets.extend([f"${e}" for e in r.get("etfs", [])])
        targets.extend([f"[{c}]" for c in r.get("commodities", [])])
        direction = r.get("direction", "neutral")
        direction_cn = "看涨" if direction == "bullish" else ("看跌" if direction == "bearish" else "中性")
        level = r.get("level", 1)
        line = f"{direction_cn} | 程度{level}/5 | {' '.join(targets) or '宏观'} | {r['reason']} (来源:{r['source']})"

        if direction != "neutral" and level >= 2:
            pushed_items.append((level, direction, line))
        else:
            filtered_items.append((level, direction, line))

    # 排序：看涨的按程度从高到低排前面，看跌的按程度从高到低排后面
    bullish = sorted([x for x in pushed_items if x[1] == "bullish"], key=lambda x: -x[0])
    bearish = sorted([x for x in pushed_items if x[1] == "bearish"], key=lambda x: -x[0])
    pushed_sorted = [x[2] for x in bullish] + [x[2] for x in bearish]
    pushed_str = "\n".join(pushed_sorted) if pushed_sorted else "今日暂无实时推送"

    # 过滤池同样排序
    filtered_sorted = sorted(filtered_items, key=lambda x: -x[0])
    filtered_str = "\n".join([x[2] for x in filtered_sorted]) if filtered_sorted else "今日无过滤文章"

    print(f"[{report_type}] 抓取市场头条...")
    headlines = fetch_market_headlines(hours=14)
    headlines_str = "\n".join(headlines) if headlines else "暂无头条"
    print(f"[{report_type}] 获取到 {len(headlines)} 条头条")

    prompt = REPORT_PROMPT.format(
        report_type=report_type,
        indices=indices_str,
        pushed_records=pushed_str,
        market_headlines=headlines_str,
        filtered_records=filtered_str,
    )

    try:
        print(f"[{report_type}] 用 DeepSeek 生成...")
        return _call_deepseek(prompt)
    except Exception as e:
        print(f"[{report_type}] DeepSeek 失败: {e}")
        return f"报告生成失败。\n\n⚠️ 以上内容仅供参考，不构成投资建议。"


def send_morning_report():
    print("[早报] 开始生成...")
    content = generate_report("早报")
    success = send_daily_report("早报", content)
    if success:
        print("[早报] 发送成功")
        clear_today_pushed()
    else:
        print("[早报] 发送失败")


def send_evening_report():
    print("[晚报] 开始生成...")
    content = generate_report("晚报")
    success = send_daily_report("晚报", content)
    if success:
        print("[晚报] 发送成功")
    else:
        print("[晚报] 发送失败")


if __name__ == "__main__":
    report_type = sys.argv[1] if len(sys.argv) > 1 else "晚报"
    if report_type == "早报":
        send_morning_report()
    else:
        send_evening_report()
