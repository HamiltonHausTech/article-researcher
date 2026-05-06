#!/usr/bin/env python3
"""Summarize candidate articles and publish a local HTML digest."""

import glob
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

import markdown2

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ARTICLES_DATA_DIR", "~/ai-digests")).expanduser()
OLLAMA_MODEL = os.environ.get("ARTICLES_OLLAMA_MODEL", "mistral")
OLLAMA_BIN = os.environ.get("ARTICLES_OLLAMA_BIN", "/usr/local/bin/ollama")
INPUT_FILE = Path(os.environ.get("ARTICLES_SOURCES_FILE", SCRIPT_DIR / "sources.json")).expanduser()
DIGEST_DIR = Path(os.environ.get("ARTICLES_DIGEST_DIR", DATA_DIR / "daily")).expanduser()
OUTPUT_FILE = DIGEST_DIR / f"{datetime.now().date()}_digest.md"
NGINX_DIR = Path(os.environ.get("ARTICLES_NGINX_DIR", "~/Projects/docker/nginx/html")).expanduser()

PROMPT_TEMPLATE = """Summarize the following article in 3-5 bullet points:
Title: {title}
URL: {url}
Content:
{content}
"""


def clean_summary(text):
    lines = [line.strip() for line in text.strip().splitlines()]
    bullets = [f"- {line}" if not line.startswith("-") else line for line in lines if line]
    return "\n".join(bullets)


def summarize_with_ollama(prompt):
    try:
        result = subprocess.run(
            [OLLAMA_BIN, "run", OLLAMA_MODEL],
            input=prompt,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()
    except FileNotFoundError:
        return f"❌ Error during summarization: Ollama binary not found at {OLLAMA_BIN}. Set ARTICLES_OLLAMA_BIN."
    except subprocess.CalledProcessError as e:
        return f"❌ Error during summarization: {e.stderr.strip()}"


def load_sources():
    if not INPUT_FILE.exists():
        raise SystemExit(f"Input file not found: {INPUT_FILE}")
    with INPUT_FILE.open("r") as f:
        return json.load(f)


def render_digest_markdown(data):
    topic = data["topic"]
    articles = data["articles"]

    lines = [f"# 🔍 Topic: {topic}", ""]
    for article in articles:
        title = article["title"]
        url = article["url"]
        content = article["content"]
        prompt = PROMPT_TEMPLATE.format(title=title, url=url, content=content)
        summary = clean_summary(summarize_with_ollama(prompt))
        lines += [f"## {title}", f"[Read more]({url})", "", summary, ""]

    return "\n".join(lines)


def wrap_html(topic, digest_markdown):
    html = markdown2.markdown(digest_markdown)
    return f"""<html>
    <head>
    <meta charset="utf-8">
    <title>{topic} Digest</title>
    </head>
    <body>
    {html}
    </body>
    </html>
"""


def publish_digest(topic, digest):
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(digest)

    digest_files = sorted(glob.glob(str(DIGEST_DIR / "*_digest.md")))
    latest_digest = Path(digest_files[-1]) if digest_files else None

    print(f"✅ Digest written to {OUTPUT_FILE}")

    if latest_digest:
        NGINX_DIR.mkdir(parents=True, exist_ok=True)
        digest_basename = OUTPUT_FILE.name
        nginx_digest_path = NGINX_DIR / digest_basename
        nginx_digest_path.write_text(wrap_html(topic, digest))

        index_path = NGINX_DIR / "index.html"
        if index_path.exists() or index_path.is_symlink():
            index_path.unlink()
        index_path.symlink_to(digest_basename)
        print(f"🔗 index.html → {digest_basename}")


def main():
    data = load_sources()
    digest = render_digest_markdown(data)
    publish_digest(data["topic"], digest)


if __name__ == "__main__":
    main()

