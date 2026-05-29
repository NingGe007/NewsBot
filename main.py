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

    # 合并推送：所有值得推的文章整合成一条消息
    if push_items:
        _send_combined_push(push_items)

    print(f"\n[完成] 推送 {pushed_count} 条，过滤噪音 {skipped_count} 条\n")


def _send_combined_push(items):
    # 按市场分组，每个市场内按程度排序
    from collections import defaultdict
    by_market = defaultdict(list)
    for item in items:
        by_market[item["market"]].append(item)

    # 统计标题
    bullish_count = sum(1 for i in items if i["direction"] == "bullish")
    bearish_count = sum(1 for i in items if i["direction"] == "bearish")
    title_parts = []
    if bullish_count:
        title_parts.append(f"🔴{bullish_count}涨")
    if bearish_count:
        title_parts.append(f"🟢{bearish_count}跌")
    title = f"📡 新信号 {' '.join(title_parts)}｜共{len(items)}条"

    # 构建正文
    sections = []
    market_order = ["美股", "A股", "港股"]
    for market in market_order:
        if market not in by_market:
            continue
        market_items = sorted(by_market[market], key=lambda x: -x["level"])
        section_lines = [f"## 【{market}】"]
        for item in market_items:
            a = item["analysis"]
            article = item["article"]
            level = item["level"]
            direction_cn = item["direction_cn"]
            bullish = item["direction"] == "bullish"
            bar = "🟥" * level + "⬜" * (5 - level) if bullish else "🟩" * level + "⬜" * (5 - level)

            section_lines.append(f"**{direction_cn} {level}/5** {bar}")
            section_lines.append(f"")
            section_lines.append(f"{a['reason']}")
            section_lines.append(f"")

            # 影响标的
            targets = []
            for t in a.get("tickers", []):
                targets.append(f"${t}")
            for s in a.get("sectors", []):
                targets.append(f"「{s}」")
            for e in a.get("etfs", []):
                targets.append(f"${e}")
            if targets:
                section_lines.append(f"**影响：** {' '.join(targets)}")
                section_lines.append(f"")

            section_lines.append(f"（{article.get('source', '')}）")
            section_lines.append(f"")
            section_lines.append(f"---")
            section_lines.append(f"")

        sections.append("\n".join(section_lines))

    body = "\n\n".join(sections)
    now = datetime.now().strftime("%H:%M")
    body = f"⏰ {now} 扫描结果\n\n{body}"

    success = send_news_alert(title, body)
    if success:
        print(f"[推送] 合并推送成功：{len(items)} 条信号")
    else:
        print(f"[推送] 合并推送失败")


if __name__ == "__main__":
    run()
