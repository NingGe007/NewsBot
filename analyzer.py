# ============================================================
# analyzer.py — DeepSeek AI 分析引擎
# ============================================================

import json
import re
import time
from openai import OpenAI
from config import DEEPSEEK_API_KEY

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

ANALYSIS_PROMPT = """你是一位专业的投资分析师，覆盖美股、A股、港股三大市场。请分析以下新闻对相关市场的影响。

新闻标题：{title}
新闻来源：{source}
所属市场：{market}
新闻内容摘要：{content}

请严格按以下JSON格式返回（只返回JSON，不要加任何解释或代码块）：

{{
  "direction": "<bullish 或 bearish 或 neutral>",
  "level": <1到5的整数，影响程度：1=很轻微，2=有点影响，3=中等影响，4=影响很大，5=重大事件>,
  "tickers": ["<相关股票代码，如AAPL、600519.SH、0700.HK>"],
  "sectors": ["<相关板块，用中文，如半导体>"],
  "etfs": ["<相关ETF代码，如QQQ>"],
  "commodities": ["<相关大宗商品，用中文，如原油>"],
  "reason": "<用中文写1-2句专业简洁的解读，说明核心逻辑和影响路径>"
}}

注意：必须返回完整JSON，tickers/sectors/etfs/commodities 无关就返回 []"""


def _parse_json(raw: str) -> dict | None:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()
    try:
        result = json.loads(raw)
        for field in ["direction", "reason", "level"]:
            if field not in result:
                return None
        result["level"] = max(1, min(5, int(result["level"])))
        result["tickers"] = result.get("tickers", [])
        result["sectors"] = result.get("sectors", [])
        result["etfs"] = result.get("etfs", [])
        result["commodities"] = result.get("commodities", [])
        return result
    except Exception:
        return None


def _call_deepseek(prompt: str) -> str | None:
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=800,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[DeepSeek] 调用失败: {e}")
        return None


def analyze_article(title: str, source: str, content: str, market: str = "美股") -> dict | None:
    prompt = ANALYSIS_PROMPT.format(
        title=title,
        source=source,
        market=market,
        content=content[:2000] if content else "（无正文摘要）"
    )

    raw = _call_deepseek(prompt)
    if raw:
        result = _parse_json(raw)
        if result:
            return result
        print("[DeepSeek] JSON解析失败，重试...")

    time.sleep(5)
    raw = _call_deepseek(prompt)
    if raw:
        return _parse_json(raw)

    return None


def should_push(analysis: dict) -> bool:
    direction = analysis.get("direction", "neutral")
    level = analysis.get("level", 1)
    if direction == "neutral":
        return False
    return level >= 2


def _level_bar(level: int, bullish: bool) -> str:
    if bullish:
        filled = "🟥" * level
        empty = "⬜" * (5 - level)
    else:
        filled = "🟩" * level
        empty = "⬜" * (5 - level)
    return f"{filled}{empty} {level}/5"


def build_push_message(article: dict, analysis: dict) -> str:
    level = analysis["level"]
    reason = analysis["reason"]
    direction = analysis["direction"]
    bullish = direction == "bullish"

    # 进度条（红涨绿跌）
    bar = _level_bar(level, bullish)

    # 相关标的（分层显示：板块 > 个股/ETF > 大宗商品）
    sectors = analysis.get("sectors", [])
    tickers = analysis.get("tickers", [])
    etfs = analysis.get("etfs", [])
    commodities = analysis.get("commodities", [])

    related_lines = []
    if sectors:
        related_lines.append(f"📂 板块：{' / '.join(sectors)}")
    if tickers or etfs:
        stocks = [f"${t}" for t in tickers] + [f"${e}" for e in etfs]
        related_lines.append(f"└ 标的：")
        related_lines.append(f"{' '.join(stocks)}")
    if commodities:
        related_lines.append(f"📦 商品：{' / '.join(commodities)}")

    parts = []
    parts.append(f"{bar}")
    parts.append(f"**{reason}**")
    if related_lines:
        parts.append("\n\n".join(related_lines))
    parts.append(f"**来源：** {article.get('source', '未知')}")
    parts.append(f"**原文：**\n{article.get('title', '')}")
    if article.get("url"):
        parts.append(f"[查看原文]({article['url']})")

    return "\n\n".join(parts)
