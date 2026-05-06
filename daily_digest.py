#!/usr/bin/env python3
"""Pick a topic, fetch article candidates, and publish the daily digest.

Configuration is intentionally environment-variable based so the same checkout
can run on a lab box, laptop, or container without editing source paths.
"""

import json
import os
import random
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ARTICLES_DATA_DIR", "~/ai-digests")).expanduser()
TOPIC_FILE = Path(os.environ.get("ARTICLES_TOPIC_FILE", DATA_DIR / "topics.txt")).expanduser()
RECENT_FILE = Path(os.environ.get("ARTICLES_RECENT_FILE", DATA_DIR / "recent.json")).expanduser()
RECENT_LIMIT = int(os.environ.get("ARTICLES_RECENT_LIMIT", "5"))
DISCOVERY_MODE = os.environ.get("ARTICLES_DISCOVERY_MODE", "feeds").strip().lower()


def load_topics():
    if not TOPIC_FILE.exists():
        raise SystemExit(
            f"Topic file not found: {TOPIC_FILE}\n"
            "Create it with one topic per line, or set ARTICLES_TOPIC_FILE."
        )
    with TOPIC_FILE.open() as f:
        topics = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    if not topics:
        raise SystemExit(f"No topics found in {TOPIC_FILE}")
    return topics


def load_recent():
    if not RECENT_FILE.exists():
        return []
    with RECENT_FILE.open() as f:
        return json.load(f)


def save_recent(recent):
    RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with RECENT_FILE.open("w") as f:
        json.dump(recent[-RECENT_LIMIT:], f, indent=2)


def pick_topic(topics, recent):
    unused = [t for t in topics if t not in recent]
    if not unused:  # all have been used recently
        unused = topics
    return random.choice(unused)


def run_fetch_and_summarize(topic):
    print(f"🔍 Selected topic: {topic}")
    if DISCOVERY_MODE == "search":
        fetch_script = "fetch_sources.py"
    elif DISCOVERY_MODE == "feeds":
        fetch_script = "feed_fetch.py"
    else:
        raise SystemExit("ARTICLES_DISCOVERY_MODE must be 'feeds' or 'search'")
    print(f"📰 Discovery mode: {DISCOVERY_MODE}")
    subprocess.run([sys.executable, str(SCRIPT_DIR / fetch_script), topic], check=True, cwd=SCRIPT_DIR)
    subprocess.run([sys.executable, str(SCRIPT_DIR / "summarize.py")], check=True, cwd=SCRIPT_DIR)


def main():
    topics = load_topics()
    recent = load_recent()
    topic = pick_topic(topics, recent)

    run_fetch_and_summarize(topic)
    recent.append(topic)
    save_recent(recent)

    print("✅ Daily digest complete.")


if __name__ == "__main__":
    main()

