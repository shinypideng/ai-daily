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
import urllib3

# RSSHub 可能有 SSL 证书问题
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────
REQUEST_TIMEOUT = 15      # 普通源最多等 15 秒
RSSHUB_TIMEOUT = 25       # RSSHub 可能慢
MAX_PER_SOURCE = 8        # 每个源最多取多少条
MAX_TOTAL = 50            # 最终每个分类输出上限（源多了）

# ── 源定义 ────────────────────────────────────────
SOURCES = [
    # ── 行业动态 ──
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
    # ── YouTube AI 频道 ──
    {
        "name": "YouTube · Two Minute Papers",
        "type": "rss",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCbfYPyITQ-7l4upoX8nvctg",
        "category": "news",
        "extractor": "youtube",
    },
    {
        "name": "YouTube · Fireship",
        "type": "rss",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCsBjURrPoezykLs9EqgamOA",
        "category": "news",
        "extractor": "youtube",
    },
    {
        "name": "YouTube · Lex Fridman",
        "type": "rss",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCSHZKyawb77ixDdsGog4iWA",
        "category": "news",
        "extractor": "youtube",
    },
    {
        "name": "YouTube · Yannic Kilcher",
        "type": "rss",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCZHmQk67mSJgfCCTn7xBfew",
        "category": "news",
        "extractor": "youtube",
    },
    {
        "name": "YouTube · TensorFlow",
        "type": "rss",
        "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC0rqucBdTuFTjJiefW5t-IQ",
        "category": "news",
        "extractor": "youtube",
    },
    # ── C端工具 ──
    {
        "name": "Reddit AI",
        "type": "rss",
        "url": "https://www.reddit.com/r/artificial/.rss",
        "category": "tool",
        "extractor": "reddit",
    },
    {
        "name": "Product Hunt",
        "type": "rss",
        "url": "https://www.producthunt.com/feed?category=ai",
        "category": "tool",
        "extractor": "producthunt",
    },
    # ── 中文平台（best-effort，可能超时）──
    {
        "name": "小红书 · AI",
        "type": "rsshub",
        "url": "https://rsshub.app/xiaohongshu/search/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD",
        "category": "tool",
        "extractor": "rsshub",
    },
    {
        "name": "抖音 · AI",
        "type": "rsshub",
        "url": "https://rsshub.app/douyin/search/%E4%BA%BA%E5%B7%A5%E6%99%BA%E8%83%BD",
        "category": "tool",
        "extractor": "rsshub",
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


def extract_youtube(entry: dict) -> Optional[dict]:
    """YouTube 频道 RSS"""
    title = (entry.get("title") or "").strip()
    url = entry.get("link", "")
    if not title or not url:
        return None
    # YouTube RSS 的 description 在 media_description 或 summary 中
    desc = entry.get("media_description", "") or entry.get("summary", "")
    return {
        "title": title,
        "url": url,
        "summary": _clean_html(desc)[:200],
        "date": _parse_date(entry.get("published") or entry.get("updated")),
        "source": "YouTube",
    }


def extract_rsshub(entry: dict) -> Optional[dict]:
    """RSSHub 通用提取（小红书/抖音等）"""
    title = (entry.get("title") or "").strip()
    url = entry.get("link", "")
    if not title or not url:
        return None
    return {
        "title": title,
        "url": url,
        "summary": _clean_html(entry.get("description", ""))[:200],
        "date": _parse_date(entry.get("pubDate") or entry.get("published")),
        "source": "RSSHub",
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

    elif src["type"] == "rsshub":
        # RSSHub 可能有 SSL 问题，用 requests 先抓再解析
        resp = requests.get(src["url"], headers=headers, timeout=RSSHUB_TIMEOUT, verify=False)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise Exception(f"RSSHub 解析失败: {feed.bozo_exception}")
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
