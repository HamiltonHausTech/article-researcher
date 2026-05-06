#!/usr/bin/env python3
from __future__ import annotations

"""Analyze one or more manually supplied article URLs.

This supports the ad-hoc workflow: "I saw this article; tell me whether it is
worth my attention and separate real signal from hype."
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from summarize import (
    ANALYSIS_DIR,
    DIGEST_DIR,
    NGINX_DIR,
    OLLAMA_MODEL,
    analyze_article,
    render_article_markdown,
    wrap_html,
)


def slugify(text: str, max_len: int = 60) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return (cleaned or "manual-analysis")[:max_len].strip("-")


def article_from_url(url: str) -> dict[str, str]:
    return {
        "title": url,
        "url": url,
        "content": "Manual URL submission. Use extracted article text if available; otherwise analyze this URL cautiously with fallback metadata.",
    }


def render_manual_markdown(topic: str, analyzed_articles: list[dict[str, Any]]) -> str:
    lines = [
        f"# Manual article analysis: {topic}",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Model: `{OLLAMA_MODEL}`",
        "",
        "This is an ad-hoc skeptical analysis of manually supplied URLs.",
        "",
    ]
    for item in analyzed_articles:
        lines += render_article_markdown(item)
    return "\n".join(lines)


def save_outputs(topic: str, analyzed_articles: list[dict[str, Any]], publish: bool) -> tuple[Path, Path | None]:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    slug = slugify(topic)

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)

    analysis_path = ANALYSIS_DIR / f"{timestamp}_{slug}.json"
    digest_path = DIGEST_DIR / f"{timestamp}_{slug}.md"

    payload = {
        "topic": topic,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": OLLAMA_MODEL,
        "manual": True,
        "articles": analyzed_articles,
    }
    analysis_path.write_text(json.dumps(payload, indent=2))

    markdown = render_manual_markdown(topic, analyzed_articles)
    digest_path.write_text(markdown)

    html_path = None
    if publish:
        NGINX_DIR.mkdir(parents=True, exist_ok=True)
        html_path = NGINX_DIR / f"{timestamp}_{slug}.html"
        html_path.write_text(wrap_html(topic, markdown))

    return digest_path, analysis_path if analysis_path.exists() else None


def print_terminal_summary(analyzed_articles: list[dict[str, Any]]) -> None:
    for item in analyzed_articles:
        analysis = item["analysis"]
        extraction = item.get("extraction", {})
        print()
        print(item.get("title") or item.get("url"))
        print(item.get("url"))
        print(
            f"Recommendation: {analysis['recommendation'].upper()} | "
            f"Signal: {analysis['signal_score']} | Fluff: {analysis['fluff_score']} | "
            f"Tech depth: {analysis['technical_depth']}"
        )
        print(
            f"Content source: {item.get('content_source', 'unknown')} | "
            f"Extraction: {extraction.get('status', 'unknown')} | "
            f"Chars: {extraction.get('content_chars', 0)}"
        )
        print(f"Summary: {analysis.get('summary', '')}")
        print(f"Skeptical take: {analysis.get('skeptical_take', '')}")
        print(f"Suggested action: {analysis.get('suggested_action', '')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Skeptically analyze manually supplied article URLs.")
    parser.add_argument("urls", nargs="+", help="Article URL(s) to analyze")
    parser.add_argument("--topic", default="manual URL review", help="Topic/context for the analysis")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Also write an HTML copy into ARTICLES_NGINX_DIR. Does not replace index.html.",
    )
    args = parser.parse_args()

    analyzed_articles = []
    for url in args.urls:
        print(f"Analyzing URL: {url}")
        analyzed_articles.append(analyze_article(args.topic, article_from_url(url)))

    digest_path, analysis_path = save_outputs(args.topic, analyzed_articles, publish=args.publish)
    print_terminal_summary(analyzed_articles)
    print()
    print(f"Digest written to: {digest_path}")
    if analysis_path:
        print(f"Analysis JSON written to: {analysis_path}")
    if args.publish:
        print(f"HTML written under: {NGINX_DIR}")


if __name__ == "__main__":
    main()
