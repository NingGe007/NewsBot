import requests
import os

WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")


def send_news_alert(title, content, direction="bullish", score=0, tickers=None, sectors=None, etfs=None, source="", link=""):
    """Send news alert via ServerChan (WeChat push)"""
    if not WEBHOOK_URL:
        print("[WARN] No WEBHOOK_URL configured, skipping push")
        return False

    try:
        resp = requests.post(WEBHOOK_URL, json={
            "title": title,
            "desp": content
        }, timeout=10)
        if resp.status_code == 200:
            print(f"[OK] ServerChan push success: {title}")
            return True
        else:
            print(f"[ERR] ServerChan push failed: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"[ERR] ServerChan push exception: {e}")
        return False


def send_daily_report(report_type, content):
    """Send daily report via ServerChan"""
    if not WEBHOOK_URL:
        print("[WARN] No WEBHOOK_URL configured, skipping push")
        return False

    msg_title = f"📊 {report_type} | NewsBot"

    try:
        resp = requests.post(WEBHOOK_URL, json={
            "title": msg_title,
            "desp": content
        }, timeout=10)
        if resp.status_code == 200:
            print(f"[OK] Daily report push success: {msg_title}")
            return True
        else:
            print(f"[ERR] Daily report push failed: {resp.status_code} {resp.text}")
            return False
    except Exception as e:
        print(f"[ERR] Daily report push exception: {e}")
        return False
