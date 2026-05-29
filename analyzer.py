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

ANALYSIS_PROMPT = """你是一个帮我盯美股新闻的老哥们。看看下面这条新闻，帮我判断一下对美股有啥影响。

新闻标题：{title}
新闻来源：{source}
新闻内容摘要：{content}

请严格按以下JSON格式返回（只返回JSON，不要加任何解释或代码块）：

{{
  "score": <1到10的整数，1=极度看跌，5=没啥影响，10=极度看涨>,
  "direction": "<bullish 或 bearish 或 neutral>",
  "tickers": ["<相关股票代码，如AAPL>"],
  "sectors": ["<相关板块，用中文，如半导体>"],
  "etfs": ["<相关ETF代码，如QQQ>"],
  "commodities": ["<相关大宗商品，用中文，如原油>"],
  "reason": "<用中文写1-2句大白话解读，就像跟哥们说'这事儿意味着xxx'>",
  "impact_level": <1到5的整数，1=屁事没有，5=大事件>
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
    return True  # DEBUG: 临时全部推送，测试完改回


def build_push_message(article: dict, analysis: dict) -> str:
    score = analysis["score"]
    reason = analysis["reason"]

    targets = []
    for ticker in analysis.get("tickers", []):
        targets.append(f"${ticker}")
    for sector in analysis.get("sectors", []):
        targets.append(f"[{sector}]")
    for etf in analysis.get("etfs", []):
        targets.append(f"${etf}")
    for commodity in analysis.get("commodities", []):
        targets.append(f"[{commodity}]")

    targets_str = " ".join(targets) if targets else ""

    parts = []
    if targets_str:
        parts.append(f"**相关：** {targets_str}")
    parts.append(f"**解读：** {reason}")
    parts.append(f"**来源：** {article.get('source', '未知')}")
    parts.append(f"**原文：** {article.get('title', '')}")
    if article.get("url"):
        parts.append(f"[查看原文]({article['url']})")

    return "\n\n".join(parts)
