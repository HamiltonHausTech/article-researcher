#!/usr/bin/env python3
from __future__ import annotations

"""Fetch recent article candidates from curated RSS/Atom feeds.

This is a deterministic, low-fluff discovery path. It writes the same
`sources.json` shape as fetch_sources.py so summarize.py can analyze/extract and
publish without knowing where candidates came from.
"""

import argparse
import calendar
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ARTICLES_DATA_DIR", "~/ai-digests")).expanduser()
FEEDS_FILE = Path(os.environ.get("ARTICLES_FEEDS_FILE", SCRIPT_DIR / "source_feeds.json")).expanduser()
SOURCES_FILE = Path(os.environ.get("ARTICLES_SOURCES_FILE", SCRIPT_DIR / "sources.json")).expanduser()
SEEN_FILE = Path(os.environ.get("ARTICLES_SEEN_FILE", DATA_DIR / "seen_urls.json")).expanduser()
DEFAULT_LIMIT = int(os.environ.get("ARTICLES_FEED_LIMIT", os.environ.get("ARTICLES_FETCH_COUNT", "6")))
DEFAULT_DAYS = int(os.environ.get("ARTICLES_FEED_DAYS", "14"))
MAX_PER_SOURCE = int(os.environ.get("ARTICLES_MAX_PER_FEED", "2"))

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}

TOPIC_KEYWORDS = {
    "ai": ["ai", "llm", "model", "agent", "inference", "rag", "copilot", "openai", "anthropic"],
    "devops": ["devops", "platform", "sre", "observability", "ci/cd", "deployment", "incident"],
    "kubernetes": ["kubernetes", "k8s", "container", "pod", "cluster", "helm", "operator"],
    "aws": ["aws", "amazon", "lambda", "eks", "ec2", "s3", "rds", "iam", "bedrock"],
    "terraform": ["terraform", "opentofu", "iac", "infrastructure as code"],
    "security": ["security", "vulnerability", "cve", "zero trust", "supply chain", "auth"],
    "data": ["data", "warehouse", "lakehouse", "iceberg", "delta", "analytics", "pipeline"],
    "local ai": ["local", "ollama", "llama.cpp", "gguf", "on-device", "private ai"],
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open() as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    path = re.sub(r"/+$", "", parsed.path) or parsed.path
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", urlencode(query), ""))


def struct_time_to_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
    except Exception:
        return None


def entry_published(entry: Any) -> datetime | None:
    return struct_time_to_datetime(getattr(entry, "published_parsed", None)) or struct_time_to_datetime(
        getattr(entry, "updated_parsed", None)
    )


def entry_text(entry: Any) -> str:
    chunks = [getattr(entry, "title", ""), getattr(entry, "summary", "")]
    tags = getattr(entry, "tags", []) or []
    chunks.extend(str(tag.get("term", "")) for tag in tags if isinstance(tag, dict))
    return "\n".join(str(chunk) for chunk in chunks if chunk)


def topic_score(topic: str, text: str, feed_tags: list[str]) -> int:
    haystack = f"{text}\n{' '.join(feed_tags)}".lower()
    topic_lower = topic.lower()
    words = [w for w in re.split(r"[^a-z0-9.+#-]+", topic_lower) if len(w) > 2]
    score = sum(8 for word in words if word in haystack)
    for category, keywords in TOPIC_KEYWORDS.items():
        if category in topic_lower:
            score += sum(5 for kw in keywords if kw in haystack)
    return score


def fetch_feed_candidates(topic: str, limit: int, days: int, include_seen: bool = False) -> list[dict[str, Any]]:
    config = load_json(FEEDS_FILE, {"feeds": []})
    seen = load_json(SEEN_FILE, {})
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    candidates = []
    by_url = {}

    for feed in config.get("feeds", []):
        parsed_feed = feedparser.parse(feed["url"])
        if parsed_feed.bozo:
            warning = str(parsed_feed.bozo_exception)
            # Some valid feeds declare a stale charset but parse fine. Keep that
            # out of the daily noise; real malformed XML/HTTP issues still show.
            if "declared as us-ascii, but parsed as utf-8" not in warning.lower():
                print(f"⚠️ Feed parse warning for {feed.get('name', feed['url'])}: {parsed_feed.bozo_exception}")
        for entry in parsed_feed.entries:
            raw_url = getattr(entry, "link", "")
            if not raw_url:
                continue
            url = normalize_url(raw_url)
            if not include_seen and url in seen:
                continue
            published = entry_published(entry)
            if published and published < cutoff:
                continue

            text = entry_text(entry)
            score = topic_score(topic, text, feed.get("tags", [])) + int(float(feed.get("weight", 0.5)) * 10)
            if published:
                age_days = max(0, (datetime.now(timezone.utc) - published).days)
                score += max(0, 14 - age_days)

            candidate = {
                "title": str(getattr(entry, "title", url)).strip(),
                "url": url,
                "content": str(getattr(entry, "summary", "")).strip(),
                "source": feed.get("name", "unknown"),
                "source_type": "feed",
                "published": published.isoformat() if published else "",
                "tags": feed.get("tags", []),
                "discovery_score": score,
            }
            previous = by_url.get(url)
            if not previous or candidate["discovery_score"] > previous["discovery_score"]:
                by_url[url] = candidate

    candidates = sorted(by_url.values(), key=lambda item: item["discovery_score"], reverse=True)
    selected = []
    per_source = {}
    for candidate in candidates:
        source = candidate.get("source", "unknown")
        if per_source.get(source, 0) >= MAX_PER_SOURCE:
            continue
        selected.append(candidate)
        per_source[source] = per_source.get(source, 0) + 1
        if len(selected) >= limit:
            return selected

    # If the source cap leaves us short, backfill from the highest-ranked
    # remaining candidates rather than producing a tiny digest.
    selected_urls = {item["url"] for item in selected}
    for candidate in candidates:
        if candidate["url"] in selected_urls:
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def update_seen(articles: list[dict[str, Any]]) -> None:
    seen = load_json(SEEN_FILE, {})
    now = datetime.now(timezone.utc).isoformat()
    for article in articles:
        url = normalize_url(article["url"])
        seen.setdefault(url, {})
        seen[url].update(
            {
                "last_seen": now,
                "title": article.get("title", ""),
                "source": article.get("source", ""),
                "published": article.get("published", ""),
            }
        )
        seen[url].setdefault("first_seen", now)
    save_json(SEEN_FILE, seen)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch candidate articles from curated RSS/Atom feeds.")
    parser.add_argument("topic", nargs="?", default="technical infrastructure", help="Topic used to rank feed items")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Maximum candidate articles")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Only include items from the last N days when dates are available")
    parser.add_argument("--include-seen", action="store_true", help="Do not suppress URLs already present in seen_urls.json")
    parser.add_argument("--no-update-seen", action="store_true", help="Do not update seen_urls.json after selecting candidates")
    args = parser.parse_args()

    print(f"Fetching curated feed candidates for: {args.topic}")
    articles = fetch_feed_candidates(args.topic, limit=args.limit, days=args.days, include_seen=args.include_seen)
    output = {"topic": args.topic, "source_mode": "feeds", "articles": articles}
    SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SOURCES_FILE.write_text(json.dumps(output, indent=2))
    if not args.no_update_seen:
        update_seen(articles)
    print(f"✅ Saved {len(articles)} feed articles to {SOURCES_FILE}")


if __name__ == "__main__":
    main()
