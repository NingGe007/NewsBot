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

ANALYSIS_PROMPT = """你是一位专业美股投资分析师。请分析以下金融新闻，判断其对美股市场的影响。

新闻标题：{title}
新闻来源：{source}
新闻内容摘要：{content}

请严格按以下JSON格式返回（只返回JSON，不要加任何解释或代码块）：

{{
  "score": <1到10的整数，1=极度看跌，5=中性/噪音，10=极度看涨>,
  "direction": "<bullish 或 bearish 或 neutral>",
  "tickers": ["<相关股票代码，如AAPL>"],
  "sectors": ["<相关板块，用中文，如半导体>"],
  "etfs": ["<相关ETF代码，如QQQ>"],
  "commodities": ["<相关大宗商品，用中文，如原油>"],
  "reason": "<用中文写1-2句直白解读，说清楚为什么看涨/看跌>",
  "impact_level": <1到5的整数，1=影响极小，5=影响极大>
}}

注意：必须返回完整JSON，tickers/sectors/etfs/commodities 无关就返回 []"""


def _parse_json(raw: str) -> dict | None:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()
    try:
        result = json.loads(raw)
        for field in ["score", "direction", "reason", "impact_level"]:
            if field not in result:
                return None
        result["score"] = int(result["score"])
        result["impact_level"] = int(result["impact_level"])
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


def analyze_article(title: str, source: str, content: str) -> dict | None:
    prompt = ANALYSIS_PROMPT.format(
        title=title,
        source=source,
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
    score = analysis.get("score", 5)
    impact = analysis.get("impact_level", 1)
    if impact < 2:
        return False
    return (1 <= score <= 4) or (7 <= score <= 10)


def format_score_emoji(score: int) -> str:
    if score >= 8:
        return "🟢🟢"
    elif score >= 7:
        return "🟢"
    elif score <= 2:
        return "🔴🔴"
    elif score <= 4:
        return "🔴"
    else:
        return "⚪"


def format_impact_stars(level: int) -> str:
    return {1: "★☆☆☆☆", 2: "★★☆☆☆", 3: "★★★☆☆", 4: "★★★★☆", 5: "★★★★★"}.get(level, "★☆☆☆☆")


def build_push_message(article: dict, analysis: dict) -> str:
    score = analysis["score"]
    direction_text = "看涨" if score >= 7 else "看跌"
    emoji = format_score_emoji(score)
    stars = format_impact_stars(analysis["impact_level"])

    targets = []
    for ticker in analysis.get("tickers", []):
        targets.append(f"${ticker}")
    for sector in analysis.get("sectors", []):
        targets.append(f"[{sector}板块]")
    for etf in analysis.get("etfs", []):
        targets.append(f"${etf}")
    for commodity in analysis.get("commodities", []):
        targets.append(f"[{commodity}]")

    targets_str = "  ".join(targets) if targets else "宏观市场"

    return "\n".join([
        f"{emoji} **{direction_text}** · 评分 {score}/10 · 影响力 {stars}",
        f"",
        f"📌 {targets_str}",
        f"📰 来源：{article.get('source', '未知')}",
        f"标题：{article.get('title', '')}",
        f"",
        f"💡 {analysis['reason']}",
        f"",
        f"🔗 {article.get('url', '')}",
    ])
