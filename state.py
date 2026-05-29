# ============================================================
# state.py — 管理已处理文章ID，防止重复推送
# ============================================================

import json
import os
from config import SEEN_IDS_FILE, MAX_SEEN_IDS


def load_seen_ids() -> set:
    """从文件加载已处理的文章ID"""
    if not os.path.exists(SEEN_IDS_FILE):
        return set()
    try:
        with open(SEEN_IDS_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("ids", []))
    except Exception:
        return set()


def save_seen_ids(ids: set):
    """保存已处理的文章ID到文件"""
    # 如果太多，删除最旧的（只保留最新的MAX_SEEN_IDS条）
    ids_list = list(ids)
    if len(ids_list) > MAX_SEEN_IDS:
        ids_list = ids_list[-MAX_SEEN_IDS:]

    with open(SEEN_IDS_FILE, "w") as f:
        json.dump({"ids": ids_list}, f)


def load_today_pushed() -> list:
    """加载今天已推送的文章记录（用于生成早晚报）"""
    filename = "today_pushed.json"
    if not os.path.exists(filename):
        return []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_today_pushed(records: list):
    """保存今天推送的文章记录"""
    with open("today_pushed.json", "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def add_today_pushed(article: dict, analysis: dict):
    """新增一条今日推送记录"""
    records = load_today_pushed()
    records.append({
        "title": article.get("title", ""),
        "url": article.get("url", ""),
        "source": article.get("source", ""),
        "market": article.get("market", "美股"),
        "direction": analysis.get("direction", "neutral"),
        "level": analysis.get("level", 1),
        "tickers": analysis.get("tickers", []),
        "sectors": analysis.get("sectors", []),
        "etfs": analysis.get("etfs", []),
        "commodities": analysis.get("commodities", []),
        "reason": analysis.get("reason", ""),
    })
    save_today_pushed(records)


def clear_today_pushed():
    """清空今日记录（每天早报发完后清空）"""
    save_today_pushed([])
