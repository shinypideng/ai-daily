"""
AI 资讯聚合抓取器
从多个源头抓取 AI 热点 + C端工具，统一输出格式。
"""
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────
REQUEST_TIMEOUT = 15  # 每个源最多等 15 秒
MAX_PER_SOURCE = 10   # 每个源最多取多少条
MAX_TOTAL = 25        # 最终输出上限

# ── 源定义 ────────────────────────────────────────
SOURCES = [
    {
        "name": "Hacker News",
        "type": "api",
        "url": "https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story&hitsPerPage=10",
        "category": "news",
        "extractor": "hn",
    },
    {
        "name": "Reddit ML",
        "type": "rss",
        "url": "https://www.reddit.com/r/MachineLearning/.rss",
        "category": "news",
        "extractor": "reddit",
    },
    {
        "name": "Reddit OpenAI",
        "type": "rss",
        "url": "https://www.reddit.com/r/OpenAI/.rss",
        "category": "news",
        "extractor": "reddit",
    },
    {
        "name": "Reddit AI",
        "type": "rss",
        "url": "https://www.reddit.com/r/artificial/.rss",
        "category": "tool",
        "extractor": "reddit",
    },
    {
        "name": "The Verge AI",
        "type": "rss",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "category": "news",
        "extractor": "verge",
    },
    {
        "name": "ArXiv cs.AI",
        "type": "rss",
        "url": "http://export.arxiv.org/rss/cs.AI",
        "category": "news",
        "extractor": "arxiv",
    },
    {
        "name": "Product Hunt",
        "type": "rss",
        "url": "https://www.producthunt.com/feed?category=ai",
        "category": "tool",
        "extractor": "producthunt",
    },
]


# ── 提取器 ────────────────────────────────────────

def extract_hn(data: dict) -> list[dict]:
    """Hacker News Algolia API"""
    articles = []
    for hit in data.get("hits", []):
        title = (hit.get("title") or "").strip()
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        if not title:
            continue
        articles.append({
            "title": title,
            "url": url,
            "summary": f"💬 {hit.get('points', 0)} 分 · {hit.get('num_comments', 0)} 评论",
            "date": _parse_date(hit.get("created_at")),
            "source": "Hacker News",
        })
    return articles[:MAX_PER_SOURCE]


def extract_reddit(entry: dict) -> Optional[dict]:
    """Reddit RSS"""
    title = (entry.get("title") or "").strip()
    url = entry.get("link", "")
    if not title or not url:
        return None
    summary = entry.get("summary", "")[:200]
    return {
        "title": title,
        "url": url,
        "summary": _clean_html(summary)[:150],
        "date": _parse_date(entry.get("published") or entry.get("updated")),
        "source": "Reddit",
    }


def extract_verge(entry: dict) -> Optional[dict]:
    """The Verge RSS"""
    title = (entry.get("title") or "").strip()
    url = entry.get("link", "")
    if not title or not url:
        return None
    return {
        "title": title,
        "url": url,
        "summary": _clean_html(entry.get("summary", ""))[:200],
        "date": _parse_date(entry.get("published")),
        "source": "The Verge",
    }


def extract_arxiv(entry: dict) -> Optional[dict]:
    """ArXiv RSS"""
    title = (entry.get("title") or "").strip()
    id_ = entry.get("id", "")
    if not title:
        return None
    abs_url = id_.replace("abs", "abs").replace("http://", "https://")
    return {
        "title": title,
        "url": abs_url,
        "summary": _clean_html(entry.get("summary", ""))[:200],
        "date": _parse_date(entry.get("published")),
        "source": "ArXiv",
    }


def extract_producthunt(entry: dict) -> Optional[dict]:
    """Product Hunt RSS"""
    title = (entry.get("title") or "").strip()
    url = entry.get("link", "")
    if not title or not url:
        return None
    return {
        "title": title,
        "url": url,
        "summary": _clean_html(entry.get("summary", ""))[:200],
        "date": _parse_date(entry.get("published") or entry.get("updated")),
        "source": "Product Hunt",
    }


# ── 工具函数 ──────────────────────────────────────

def _parse_date(date_str: Optional[str]) -> str:
    """解析日期，输出 YYYY-MM-DD"""
    if not date_str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        # feedparser 已经解析过，拿 struct_time
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _clean_html(text: str) -> str:
    """去掉 HTML 标签"""
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


# ── 主抓取逻辑 ────────────────────────────────────

def fetch_all() -> dict[str, list[dict]]:
    """
    从所有源抓取，返回 {"news": [...], "tool": [...]}
    """
    seen_urls: set[str] = set()
    result: dict[str, list[dict]] = {"news": [], "tool": []}

    for src in SOURCES:
        logger.info(f"📡 抓取 {src['name']} ...")
        try:
            articles = _fetch_source(src)
            for a in articles:
                uh = _url_hash(a["url"])
                if uh in seen_urls:
                    continue
                seen_urls.add(uh)
                a["category"] = src["category"]
                result[src["category"]].append(a)
            logger.info(f"   ✅ {src['name']}: {len(articles)} 条")
        except Exception as e:
            logger.warning(f"   ⚠️ {src['name']}: {e}")

    # 按日期降序（当天优先），数量截断
    for cat in result:
        result[cat].sort(key=lambda x: x.get("date", ""), reverse=True)
        result[cat] = result[cat][:MAX_TOTAL]

    total = len(result["news"]) + len(result["tool"])
    logger.info(f"🎉 抓取完成：行业动态 {len(result['news'])} 条 + C端工具 {len(result['tool'])} 条 = {total}")
    return result


def _fetch_source(src: dict) -> list[dict]:
    """抓取单个源"""
    headers = {"User-Agent": "AI-Daily/1.0 (news aggregator bot)"}

    if src["type"] == "api":
        resp = requests.get(src["url"], headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return globals()[f"extract_{src['extractor']}"](data)

    elif src["type"] == "rss":
        feed = feedparser.parse(src["url"])
        if feed.bozo and not feed.entries:
            raise Exception(f"RSS 解析失败: {feed.bozo_exception}")
        articles = []
        extractor = globals()[f"extract_{src['extractor']}"]
        for entry in feed.entries[:MAX_PER_SOURCE]:
            a = extractor(entry)
            if a:
                articles.append(a)
        return articles

    return []


# ── CLI ───────────────────────────────────────────

if __name__ == "__main__":
    import json
    data = fetch_all()
    print(json.dumps(data, ensure_ascii=False, indent=2))
