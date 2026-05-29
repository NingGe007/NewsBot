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

    for article in new_articles:
        print(f"\n[分析] {article['title'][:60]}...")
        print(f"       来源: {article.get('source', '未知')}")

        content = article.get("summary", "")
        if len(content) < 100 and article.get("url"):
            print(f"       摘要太短，抓取正文...")
            content = fetch_article_content(article["url"])

        analysis = analyze_article(
            title=article["title"],
            source=article.get("source", ""),
            content=content
        )

        if not analysis:
            print(f"       [跳过] AI分析失败")
            seen_ids.add(article["id"])
            continue

        score = analysis["score"]
        impact = analysis["impact_level"]
        print(f"       评分: {score}/10  影响力: {impact}/5")

        # 所有分析结果都记录，供日报汇总
        add_today_pushed(article, analysis)

        if should_push(analysis):
            message = build_push_message(article, analysis)
            # 中国股市惯例：红涨绿跌，标题只显示方向和评分
            if score >= 7:
                title = f"🔴 看涨 {score}/10"
            else:
                title = f"🟢 看跌 {score}/10"

            success = send_news_alert(title, message)
            if success:
                pushed_count += 1
                print(f"       已推送到飞书")
            else:
                print(f"       推送飞书失败")
        else:
            skipped_count += 1
            print(f"       [过滤] 评分 {score}，市场噪音")

        seen_ids.add(article["id"])
        time.sleep(1)

    save_seen_ids(seen_ids)

    print(f"\n[完成] 推送 {pushed_count} 条，过滤噪音 {skipped_count} 条\n")


if __name__ == "__main__":
    run()
