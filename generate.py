"""
AI 每日速递 — 主生成脚本
调用 fetcher 抓取资讯 → Jinja2 渲染 → 输出静态 HTML
"""
import os
import sys
from datetime import datetime, timezone

from jinja2 import Environment, FileSystemLoader

# 添加当前目录到 path，方便 import fetcher
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetcher import fetch_all

# 项目根目录
ROOT = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(ROOT, "templates")
OUTPUT = os.path.join(ROOT, "docs", "index.html")


SOURCE_LABELS = {
    "Hacker News": "HN",
    "The Verge": "Verge",
    "Reddit": "Reddit",
    "ArXiv": "ArXiv",
    "Product Hunt": "PH",
}


def main():
    print("=" * 50)
    print("  AI 每日速递 — 开始生成")
    print("=" * 50)

    # 1. 抓取
    print("\n📡 正在抓取资讯...\n")
    data = fetch_all()

    # 2. 处理数据
    news = _enrich(data.get("news", []))
    tool = _enrich(data.get("tool", []))

    # 收集来源
    news_sources = sorted(set(a["source"] for a in news))
    tool_sources = sorted(set(a["source"] for a in tool))

    # 3. 渲染
    print(f"\n🎨 渲染 HTML...")
    env = Environment(loader=FileSystemLoader(TEMPLATES))
    template = env.get_template("index.html")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    html = template.render(
        date=today,
        news=news,
        tool=tool,
        sources={"news": news_sources, "tool": tool_sources},
    )

    # 4. 输出
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ 已生成: {OUTPUT}")
    print(f"   📰 行业动态: {len(news)} 条")
    print(f"   🛠️  C端工具: {len(tool)} 条")
    print("=" * 50)


def _enrich(articles: list[dict]) -> list[dict]:
    """给文章加 source_label 用于 CSS 类名"""
    for a in articles:
        a["source_label"] = SOURCE_LABELS.get(a.get("source", ""), "Other")
    return articles


if __name__ == "__main__":
    main()
