# ============================================================
# main.py — 主监控脚本
# ============================================================

import time
import os
from datetime import datetime

from scraper import get_latest_articles, fetch_article_content
from analyzer import analyze_article, should_push, build_push_message
from feishu import send_news_alert
from state import load_seen_ids, save_seen_ids, add_today_pushed


def ensure_state_files():
    if not os.path.exists("today_pushed.json"):
        with open("today_pushed.json", "w") as f:
            f.write("[]")
    if not os.path.exists("seen_ids.json"):
        with open("seen_ids.json", "w") as f:
            f.write('{"ids": []}')


def run():
    print(f"\n{'='*50}")
    print(f"[运行时间] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    ensure_state_files()

    seen_ids = load_seen_ids()
    is_first_run = len(seen_ids) == 0
    print(f"[状态] 已有 {len(seen_ids)} 条历史记录")

    if is_first_run:
        print("[首次运行] 只标记文章，不分析")

    articles = get_latest_articles()
    if not articles:
        print("[结果] 本次未抓到文章")
        return

    new_articles = [a for a in articles if a["id"] not in seen_ids]
    print(f"[去重] 新文章 {len(new_articles)} 篇（共 {len(articles)} 篇）")

    if not new_articles:
        print("[结果] 无新文章，本次结束")
        return

    if is_first_run:
        for article in new_articles:
            seen_ids.add(article["id"])
        save_seen_ids(seen_ids)
        print(f"[首次运行完成] 已标记 {len(new_articles)} 篇，下次运行开始推送")
        return

    pushed_count = 0
    skipped_count = 0
    push_items = []

    for article in new_articles:
        print(f"\n[分析] {article['title'][:60]}...")
        print(f"       来源: {article.get('source', '未知')}")

        content = article.get("summary", "")
        if len(content) < 100 and article.get("url"):
            print(f"       摘要太短，抓取正文...")
            content = fetch_article_content(article["url"])

        market = article.get("market", "美股")
        analysis = analyze_article(
            title=article["title"],
            source=article.get("source", ""),
            content=content,
            market=market
        )

        if not analysis:
            print(f"       [跳过] AI分析失败")
            seen_ids.add(article["id"])
            continue

        level = analysis["level"]
        direction = analysis["direction"]
        direction_cn = "看涨" if direction == "bullish" else ("看跌" if direction == "bearish" else "中性")
        print(f"       方向: {direction_cn}  程度: {level}/5")

        # 所有分析结果都记录，供日报汇总
        add_today_pushed(article, analysis)

        if should_push(analysis):
            push_items.append({
                "article": article,
                "analysis": analysis,
                "market": market,
                "direction": direction,
                "direction_cn": direction_cn,
                "level": level,
            })
            pushed_count += 1
            print(f"       待推送")
        else:
            skipped_count += 1
            print(f"       [过滤] {direction_cn} {level}/5，不够重要")

        seen_ids.add(article["id"])
        time.sleep(1)

    save_seen_ids(seen_ids)

    # 按市场分组推送：A股+港股一条，美股一条
    if push_items:
        cn_items = [i for i in push_items if i["market"] in ("A股", "港股")]
        us_items = [i for i in push_items if i["market"] == "美股"]
        if cn_items:
            _send_grouped_push(cn_items, "A股/港股")
        if us_items:
            _send_grouped_push(us_items, "美股")

    print(f"\n[完成] 推送 {pushed_count} 条，过滤噪音 {skipped_count} 条\n")


def _fetch_ticker_quote(symbol: str) -> dict | None:
    """查询单个股票当日涨跌，返回 {pct, text}"""
    import requests
    ticker = symbol.upper().strip()
    if ticker.endswith(".SH"):
        yahoo_sym = ticker.replace(".SH", ".SS")
    elif ticker.endswith(".HK"):
        num = ticker.replace(".HK", "").lstrip("0")
        yahoo_sym = f"{int(num):04d}.HK"
    else:
        yahoo_sym = ticker

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}?interval=1d&range=2d"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = resp.json()
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        prev_close = meta.get("chartPreviousClose", 0)
        if prev_close and price:
            pct = ((price - prev_close) / prev_close) * 100
            return {"pct": pct}
    except Exception:
        pass
    return None


def _format_quote(ticker: str, quote_data) -> str:
    """格式化 ticker 行情：红涨绿跌"""
    if not quote_data:
        return f"${ticker}"
    pct = quote_data["pct"]
    if pct >= 0:
        return f"🔴${ticker}↑{abs(pct):.2f}%"
    else:
        return f"🟢${ticker}↓{abs(pct):.2f}%"


def _send_grouped_push(items, group_name):
    """按市场分组合并推送，精简格式，带个股涨跌"""
    import time as _time
    from collections import defaultdict

    # 只推 top 5，按 level 排序
    items = sorted(items, key=lambda x: -x["level"])[:5]

    # 收集所有 ticker，批量查行情
    all_tickers = []
    for item in items:
        all_tickers.extend(item["analysis"].get("tickers", []))
        all_tickers.extend(item["analysis"].get("etfs", []))
    all_tickers = list(set(all_tickers))

    quotes = {}  # {ticker: {pct: float}}
    for ticker in all_tickers:
        qdata = _fetch_ticker_quote(ticker)
        if qdata:
            quotes[ticker] = qdata
        _time.sleep(0.5)

    bullish_count = sum(1 for i in items if i["direction"] == "bullish")
    bearish_count = sum(1 for i in items if i["direction"] == "bearish")
    title_parts = []
    if bullish_count:
        title_parts.append(f"🔴{bullish_count}涨")
    if bearish_count:
        title_parts.append(f"🟢{bearish_count}跌")
    title = f"📡 {group_name} {' '.join(title_parts)}"

    # 按市场子分组
    by_market = defaultdict(list)
    for item in items:
        by_market[item["market"]].append(item)

    lines = []
    for market in ["A股", "港股", "美股"]:
        if market not in by_market:
            continue
        market_items = sorted(by_market[market], key=lambda x: -x["level"])
        if len(by_market) > 1:
            lines.append(f"**【{market}】**")
            lines.append("")

        for item in market_items:
            a = item["analysis"]
            level = item["level"]
            direction_cn = item["direction_cn"]
            bullish = item["direction"] == "bullish"
            icon = "🔴" if bullish else "🟢"

            # 检测方向和实际涨跌是否矛盾
            conflict = False
            tickers_list = a.get("tickers", []) + a.get("etfs", [])
            for t in tickers_list:
                qdata = quotes.get(t)
                if qdata:
                    if bullish and qdata["pct"] < -1:
                        conflict = True
                        break
                    elif not bullish and qdata["pct"] > 1:
                        conflict = True
                        break

            # 第一行：方向 + 程度 + 矛盾警告
            warn = " ⚠️" if conflict else ""
            lines.append(f"{icon} **{direction_cn} {level}/5**{warn}")
            lines.append("")

            # 第二行：原因解读
            lines.append(f"{a['reason']}")
            lines.append("")

            # 第三行：相关标的带行情（红涨绿跌，去重）
            targets = []
            seen_tickers = set()
            for t in a.get("tickers", []):
                if t not in seen_tickers:
                    seen_tickers.add(t)
                    targets.append(_format_quote(t, quotes.get(t)))
            for e in a.get("etfs", []):
                if e not in seen_tickers:
                    seen_tickers.add(e)
                    targets.append(_format_quote(e, quotes.get(e)))
            for s in a.get("sectors", []):
                targets.append(f"「{s}」")
            if targets:
                lines.append(f"📌 {' | '.join(targets)}")
                lines.append("")

            lines.append("---")
            lines.append("")

    now = datetime.now().strftime("%H:%M")
    body = f"⏰ {now}\n\n" + "\n".join(lines)

    success = send_news_alert(title, body)
    if success:
        print(f"[推送] {group_name} 合并推送成功：{len(items)} 条信号")
    else:
        print(f"[推送] {group_name} 合并推送失败")


if __name__ == "__main__":
    run()
