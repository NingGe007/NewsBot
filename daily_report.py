# ============================================================
# daily_report.py — 每日早报/晚报（DeepSeek 引擎）
# ============================================================

import json
import sys
import time
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


def _convert_ticker_to_yahoo(ticker: str) -> str:
    """将分析器输出的股票代码转换为 Yahoo Finance 格式"""
    ticker = ticker.upper().strip()
    if ticker.endswith(".SH"):
        return ticker.replace(".SH", ".SS")
    if ticker.endswith(".SZ"):
        return ticker
    if ticker.endswith(".HK"):
        num = ticker.replace(".HK", "").lstrip("0")
        return f"{int(num):04d}.HK"
    return ticker


def _fetch_ticker_quote(symbol: str) -> dict | None:
    """查询单个股票的当日涨跌"""
    yahoo_symbol = _convert_ticker_to_yahoo(symbol)
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?interval=1d&range=2d"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = resp.json()
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("chartPreviousClose", 0)
        currency = meta.get("currency", "USD")
        if prev_close and price:
            change_pct = ((price - prev_close) / prev_close) * 100
            return {
                "symbol": symbol,
                "price": price,
                "change_pct": change_pct,
                "currency": currency,
            }
    except Exception:
        pass
    return None


def fetch_ticker_quotes(tickers: list[str]) -> dict[str, dict]:
    """批量查询股票行情，返回 {ticker: quote_info}"""
    quotes = {}
    seen = set()
    for ticker in tickers:
        if ticker in seen:
            continue
        seen.add(ticker)
        quote = _fetch_ticker_quote(ticker)
        if quote:
            quotes[ticker] = quote
        time.sleep(0.5)
    return quotes


def format_ticker_with_quote(ticker: str, quotes: dict) -> str:
    """格式化单个 ticker 带行情：$NVDA ↑3.52%"""
    q = quotes.get(ticker)
    if not q:
        return f"${ticker}"
    pct = q["change_pct"]
    arrow = "↑" if pct >= 0 else "↓"
    return f"${ticker} {arrow}{abs(pct):.2f}%"


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


REPORT_PROMPT = """你是我的一个炒美股的老哥们，每天帮我盯盘。现在请用朋友聊天的口吻，给我发一条{report_type}消息。

要求：
- 说人话，别用分析师那套官话
- 像微信群里老股民聊天一样，直白、接地气
- 该说"牛逼"就说"牛逼"，该说"拉胯"就说"拉胯"
- 重点说清楚：今天涨了还是跌了、为啥、明天要注意啥
- 如果有我该关注的机会或风险，直接说"兄弟你看看这个"
- 看涨/看跌信号里，每个 ticker 后面带上今日实际涨跌幅（我已经帮你查好了）

数据参考：

三大指数：{indices}

今日已推送的信号（带实时行情）：
{pushed_records}

市场头条：
{market_headlines}

今日被过滤的文章分析（帮我扫一眼有没有值得关注的）：
{filtered_records}

格式大概这样（不用完全一样，自然就行）：

📊 三大指数：（一句话说涨跌）

🔴 **看涨信号**
- $TICKER ↑X.XX% — 看涨 N/5
  事件：xxx发生了什么
  逻辑：为什么利好，传导路径是啥
  预期：短期怎么看
（每条信号要把事件、逻辑、预期说清楚，2-3行。无则写"暂无"）

🟢 **看跌信号**
- $TICKER ↓X.XX% — 看跌 N/5
  事件/逻辑/预期同上
（无则写"暂无"）

💰 机会/风险提醒：
- （有就说，没有就说"今天没啥特别的，观望就行"）

📌 明天注意：
- （有啥要关注的提前说一嘴）

📋 过滤池里捞出来的：
- （如果被过滤的文章里有值得注意的，列1-3条。都是垃圾就不提）

⚠️ 纯聊天不构成投资建议，亏了别找我哈

控制在 800 字以内。每条信号要写清楚逻辑，但别啰嗦。"""


def _call_deepseek(prompt: str) -> str:
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1800,
    )
    return response.choices[0].message.content.strip()


def generate_report(report_type: str, market_group: str = "all") -> str:
    """
    market_group: "us" = 美股, "cn" = A股+港股, "all" = 全部
    """
    group_label = {"us": "美股", "cn": "A股/港股", "all": "全市场"}[market_group]
    print(f"[{report_type}:{group_label}] 抓取指数数据...")
    indices_str = fetch_market_indices()
    print(f"[{report_type}:{group_label}] 指数: {indices_str}")

    all_records = load_today_pushed()

    # 按市场分组过滤
    if market_group == "us":
        records = [r for r in all_records if r.get("market", "美股") == "美股"]
    elif market_group == "cn":
        records = [r for r in all_records if r.get("market", "美股") in ("A股", "港股")]
    else:
        records = all_records

    if not records:
        return f"今日{group_label}暂无信号推送。\n\n⚠️ 纯聊天不构成投资建议，亏了别找我哈"

    # 收集所有涉及的 ticker，批量查行情
    all_tickers = []
    for r in records:
        all_tickers.extend(r.get("tickers", []))
        all_tickers.extend(r.get("etfs", []))
    all_tickers = list(set(all_tickers))

    quotes = {}
    if all_tickers:
        print(f"[{report_type}] 查询 {len(all_tickers)} 个标的行情...")
        quotes = fetch_ticker_quotes(all_tickers)
        print(f"[{report_type}] 成功获取 {len(quotes)} 个标的数据")

    pushed_items = []
    filtered_items = []
    for r in records:
        # 构建带行情的标的列表
        targets = []
        for t in r.get("tickers", []):
            targets.append(format_ticker_with_quote(t, quotes))
        for s in r.get("sectors", []):
            targets.append(f"「{s}板块」")
        for e in r.get("etfs", []):
            targets.append(format_ticker_with_quote(e, quotes))
        for c in r.get("commodities", []):
            targets.append(f"[{c}]")

        direction = r.get("direction", "neutral")
        direction_cn = "看涨" if direction == "bullish" else ("看跌" if direction == "bearish" else "中性")
        level = r.get("level", 1)
        line = f"{direction_cn} {level}/5 | {' '.join(targets) or '宏观'} | {r['reason']} (来源:{r['source']})"

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
        report_type=f"{group_label}{report_type}",
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
    # A股/港股早报
    content_cn = generate_report("早报", market_group="cn")
    success_cn = send_daily_report("A股/港股早报", content_cn)
    if success_cn:
        print("[早报] A股/港股发送成功")

    # 美股早报
    content_us = generate_report("早报", market_group="us")
    success_us = send_daily_report("美股早报", content_us)
    if success_us:
        print("[早报] 美股发送成功")

    if success_cn or success_us:
        clear_today_pushed()
    else:
        print("[早报] 全部发送失败")


def send_evening_report():
    print("[晚报] 开始生成...")
    # A股/港股晚报
    content_cn = generate_report("晚报", market_group="cn")
    success_cn = send_daily_report("A股/港股晚报", content_cn)
    if success_cn:
        print("[晚报] A股/港股发送成功")

    # 美股晚报
    content_us = generate_report("晚报", market_group="us")
    success_us = send_daily_report("美股晚报", content_us)
    if success_us:
        print("[晚报] 美股发送成功")

    if not success_cn and not success_us:
        print("[晚报] 全部发送失败")


if __name__ == "__main__":
    report_type = sys.argv[1] if len(sys.argv) > 1 else "晚报"
    if report_type == "早报":
        send_morning_report()
    else:
        send_evening_report()
