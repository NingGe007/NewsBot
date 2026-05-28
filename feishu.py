import requests
import os

WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")

def send_news_alert(title, content, direction="bullish", score=0, tickers=None, sectors=None, etfs=None, source="", link=""):
    """Send news alert via ServerChan (WeChat push)"""
    if not WEBHOOK_URL:
        print("[WARN] No WEBHOOK_URL configured, skipping push")
        return

    # Build message
    emoji = "🟢📈" if direction == "bullish" else "🔴📉"
    direction_cn = "看涨" if direction == "bullish" else "看跌"

    msg_title = f"{emoji} {direction_cn} {score}/10 | {title[:50]}"

    desp_parts = [
        f"## {emoji} {direction_cn}信号 · 评分 {score}/10",
        f"标题: {title}",
        f"来源: {source}",
    ]

    if tickers:
        desp_parts.append(f"相关股票: {', '.join(tickers) if isinstance(tickers, list) else tickers}")
    if sectors:
        desp_parts.append(f"板块: {', '.join(sectors) if isinstance(sectors, list) else sectors}")
    if etfs:
        desp_parts.append(f"ETF: {', '.join(etfs) if isinstance(etfs, list) else etfs}")
    if content:
        desp_parts.append(f"\n分析: {content}")
    if link:
        desp_parts.append(f"\n[📰 原文链接]({link})")

    desp = "\n\n".join(desp_parts)

    try:
        resp = requests.post(WEBHOOK_URL, json={
            "title": msg_title,
            "desp": desp
        }, timeout=10)
        if resp.status_code == 200:
            print(f"[OK] ServerChan push success: {msg_title}")
        else:
            print(f"[ERR] ServerChan push failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[ERR] ServerChan push exception: {e}")


def send_daily_report(report_type, content):
    """Send daily report via ServerChan"""
    if not WEBHOOK_URL:
        print("[WARN] No WEBHOOK_URL configured, skipping push")
        return

    msg_title = f"📊 美股{report_type} | NewsBot"

    try:
        resp = requests.post(WEBHOOK_URL, json={
            "title": msg_title,
            "desp": content
        }, timeout=10)
        if resp.status_code == 200:
            print(f"[OK] Daily report push success")
        else:
            print(f"[ERR] Daily report push failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[ERR] Daily report push exception: {e}")
