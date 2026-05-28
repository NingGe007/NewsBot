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


REPORT_PROMPT = """你是一位专业的美股投资分析师，请生成一份简洁的{report_type}，供美股个人投资者（资金约1万美金，长中短线都做）阅读。

今日三大指数表现：
{indices}

今日已推送的信号（必须全部列入关键影响一览）：
{pushed_records}

今日市场头条（用于补充市场背景）：
{market_headlines}

请用中文生成报告（ticker/公司名/专有名词保持英文），严格按以下格式，每个板块用bullet point呈现：

**今日市场概览**
- {indices_bullet}（直接写三大指数涨跌数据）
- 今日整体市场氛围：（risk-on还是risk-off，1句话）
- 主要驱动力：（1句话）

---

**关键影响一览**
🟢 看涨信号：
- $TICKER 或 [板块] — 一句话原因
（今日推送记录里所有看涨的都要列出，没有就写"· 暂无"）
🔴 看跌信号：
- $TICKER 或 [板块] — 一句话原因
（今日推送记录里所有看跌的都要列出，没有就写"· 暂无"）

---

**行业 & 板块速览**
- [板块名]：一句话动态
- [板块名]：一句话动态
（从头条提炼3-5个板块）

---

**大宗商品 & 汇率**
- 原油：（有数据就写，没有写"暂无"）
- 黄金：（有数据就写，没有写"暂无"）
- 美元：（有数据就写，没有写"暂无"）

---

**地缘 & 监管**
- （有就写1-2条bullet，没有写"· 暂无"）

---

⚠️ 以上内容仅供参考，不构成投资建议。

注意：整体控制在400字以内，语言傻瓜直白"""


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
    if records:
        records_summary = []
        for r in records:
            targets = []
            targets.extend([f"${t}" for t in r.get("tickers", [])])
            targets.extend([f"[{s}板块]" for s in r.get("sectors", [])])
            targets.extend([f"${e}" for e in r.get("etfs", [])])
            targets.extend([f"[{c}]" for c in r.get("commodities", [])])
            direction = "看涨" if r["score"] >= 7 else "看跌"
            records_summary.append(
                f"{direction} | {' '.join(targets) or '宏观'} | {r['reason']} (来源:{r['source']})"
            )
        pushed_str = "\n".join(records_summary)
    else:
        pushed_str = "今日暂无推送记录"

    print(f"[{report_type}] 抓取市场头条...")
    headlines = fetch_market_headlines(hours=14)
    headlines_str = "\n".join(headlines) if headlines else "暂无头条"
    print(f"[{report_type}] 获取到 {len(headlines)} 条头条")

    prompt = REPORT_PROMPT.format(
        report_type=report_type,
        indices=indices_str,
        indices_bullet=indices_str,
        pushed_records=pushed_str,
        market_headlines=headlines_str,
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
