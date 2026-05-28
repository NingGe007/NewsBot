# ============================================================
# config.py — 所有配置都在这里
# ============================================================

import os

FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")

ALLOWED_SOURCES = [
    "sec filing", "sec", "earnings report", "earnings",
    "fda approval", "fda", "ipo filing", "ipo",
    "government contract", "gov contract",
    "bloomberg", "reuters", "wall street journal", "wsj", "cnbc",
    "brief", "briefs", "marketwatch", "yahoo finance",
]

BLOCKED_SOURCES = [
    "barrons", "barron's", "s&p global",
    "press release", "earnings call transcript", "transcript",
]

PUSH_SCORE_MIN = 1
PUSH_SCORE_MAX = 4
PUSH_BULLISH_MIN = 7
PUSH_BULLISH_MAX = 10

MORNING_REPORT_HOUR = 8
EVENING_REPORT_HOUR = 20

NEWSFILTER_BASE_URL = "https://newsfilter.io"
FETCH_INTERVAL_MINUTES = 20
REQUEST_DELAY_SECONDS = 1

SEEN_IDS_FILE = "seen_ids.json"
MAX_SEEN_IDS = 3000
