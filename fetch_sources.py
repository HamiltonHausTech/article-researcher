#!/usr/bin/env python3
"""Find candidate articles for a topic using OpenAI web search."""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCES_FILE = Path(os.environ.get("ARTICLES_SOURCES_FILE", SCRIPT_DIR / "sources.json")).expanduser()
OPENAI_MODEL = os.environ.get("ARTICLES_OPENAI_MODEL", "gpt-4.1")
DEFAULT_ARTICLE_COUNT = int(os.environ.get("ARTICLES_FETCH_COUNT", "4"))

today = datetime.today().strftime("%B %d, %Y")

load_dotenv(SCRIPT_DIR / ".env")
load_dotenv()
client = OpenAI()


def extract_json_block(text):
    """Extract a JSON array from either a fenced block or raw response text."""
    match = re.search(r"```(?:json)?\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return json.loads(match.group(1))
    return json.loads(text)


def fetch_articles(topic, n=DEFAULT_ARTICLE_COUNT):
    prompt = (
        f"As of {today}, find {n} recent, high-quality technical articles on the topic \"{topic}\" "
        "that were published in the last 45 days. Prioritize current events, recent advancements, "
        "or timely discussions. Exclude content older than 2 months. Prefer articles with concrete "
        "technical details over vendor announcements, SEO explainers, or generic trend pieces. "
        "Return a JSON array with this exact format: "
        "[{\"title\": ..., \"url\": ..., \"content\": \"3-5 paragraph summary or excerpt\"}]."
    )
    resp = client.responses.create(
        model=OPENAI_MODEL,
        tools=[{"type": "web_search_preview"}],
        input=prompt,
    )
    try:
        return extract_json_block(resp.output_text)
    except json.JSONDecodeError:
        print("⚠️ Could not parse JSON from response:")
        print(resp.output_text[:1000])
        sys.exit(1)


def main():
    topic = " ".join(sys.argv[1:]) or input("Topic? ").strip()
    print(f"Fetching sources for: {topic}")
    articles = fetch_articles(topic)
    output = {"topic": topic, "articles": articles}
    SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with SOURCES_FILE.open("w") as f:
        json.dump(output, f, indent=2)
    print(f"✅ Saved {len(articles)} articles to {SOURCES_FILE}")


if __name__ == "__main__":
    main()

