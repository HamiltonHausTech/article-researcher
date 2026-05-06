#!/usr/bin/env python3
from __future__ import annotations

"""Analyze candidate articles and publish a local HTML digest.

This is intentionally a triage step, not just a summarizer. It scores each
candidate for signal, fluff, relevance, novelty, and technical depth, then
renders a decision-oriented digest that protects the reader's attention.
"""

import glob
import html as html_lib
import json
import os
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import markdown2

from article_extractor import extract_article

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("ARTICLES_DATA_DIR", "~/ai-digests")).expanduser()
OLLAMA_MODEL = os.environ.get("ARTICLES_OLLAMA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_HOST = os.environ.get("ARTICLES_OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_TIMEOUT = int(os.environ.get("ARTICLES_OLLAMA_TIMEOUT", "300"))
EXTRACT_TIMEOUT = int(os.environ.get("ARTICLES_EXTRACT_TIMEOUT", "20"))
INPUT_FILE = Path(os.environ.get("ARTICLES_SOURCES_FILE", SCRIPT_DIR / "sources.json")).expanduser()
DIGEST_DIR = Path(os.environ.get("ARTICLES_DIGEST_DIR", DATA_DIR / "daily")).expanduser()
ANALYSIS_DIR = Path(os.environ.get("ARTICLES_ANALYSIS_DIR", DATA_DIR / "analysis")).expanduser()
OUTPUT_FILE = DIGEST_DIR / f"{datetime.now().date()}_digest.md"
ANALYSIS_FILE = ANALYSIS_DIR / f"{datetime.now().date()}_analysis.json"
NGINX_DIR = Path(os.environ.get("ARTICLES_NGINX_DIR", "~/Projects/docker/nginx/html")).expanduser()

VALID_RECOMMENDATIONS = {"read", "skim", "watch", "ignore"}

ANALYSIS_PROMPT = """You are a skeptical technical analyst filtering articles for a senior DevOps/platform engineer.

The reader is interested in practical infrastructure, AWS, Kubernetes, Terraform, DevOps/platform engineering, AI agents/tools, local/private AI, data infrastructure, security/ops risk, and useful emerging technology.

The reader has limited time and dislikes vendor fluff, generic trend pieces, SEO explainers, recycled content, and ungrounded hype.

Analyze the article candidate below. Decide whether it is worth the reader's attention. Separate technically meaningful claims from marketing language. Penalize thin vendor announcements and generic trend content. Prefer concrete technical details, independent evidence, operational lessons, architecture, benchmarks, failure modes, and practical implications.

Important limitation: the content_source field says whether the text is extracted article text or only a search-generated excerpt/summary. If evidence is thin, reflect that in the scores and claims_to_verify. Be more confident when content_source is extracted_article_text and extraction_status is ok.

Return strict JSON only with exactly these keys:
{
  "recommendation": "read|skim|watch|ignore",
  "signal_score": 0,
  "fluff_score": 0,
  "technical_depth": 0,
  "novelty": 0,
  "relevance": 0,
  "summary": "concise plain-English summary",
  "why_selected": "one sentence explaining why it made the digest or why it barely did",
  "technically_sound_claims": ["..."],
  "marketing_or_hype": ["..."],
  "claims_to_verify": ["..."],
  "why_it_matters_to_me": ["..."],
  "skeptical_take": "short, direct, opinionated take",
  "suggested_action": "what the reader should do with this",
  "tags": ["..."]
}

Scoring guide:
- signal_score: 85-100 read, 70-84 skim, 55-69 watch/maybe, below 55 ignore.
- fluff_score: 0 is no fluff, 100 is pure marketing/SEO/vendor ad.
- Penalize vendor press releases, generic AI trend articles, no concrete examples, old/stale items, and recycled listicles.

Topic: {topic}
Title: {title}
URL: {url}
Source metadata:
{metadata}

Content source: {content_source}
Extraction status: {extraction_status}

Content:
{content}
"""


def clamp_score(value: Any, default: int = 0) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, score))


def ensure_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def strip_spinner_noise(text: str) -> str:
    # Ollama's non-PTY output can include unicode spinner frames before content.
    return re.sub(r"^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏\s]+", "", text.strip())


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = strip_spinner_noise(text)

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1))

    # Some reasoning models emit hidden/thinking preamble. Use the first complete
    # top-level JSON object we can decode.
    decoder = json.JSONDecoder()
    for idx, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(cleaned[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj

    raise json.JSONDecodeError("No JSON object found", cleaned, 0)


def analyze_with_ollama(prompt: str) -> dict[str, Any]:
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.1},
        }
        request = urllib.request.Request(
            f"{OLLAMA_HOST}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
        model_output = body.get("response", "")
        return normalize_analysis(extract_json_object(model_output), raw_output=model_output)
    except (TimeoutError, socket.timeout):
        return error_analysis(f"Ollama timed out after {OLLAMA_TIMEOUT}s using model {OLLAMA_MODEL}.")
    except urllib.error.URLError as e:
        return error_analysis(f"Ollama API failed at {OLLAMA_HOST}: {e}")
    except json.JSONDecodeError as e:
        return error_analysis(f"Could not parse model JSON: {e}")


def error_analysis(message: str) -> dict[str, Any]:
    return {
        "recommendation": "ignore",
        "signal_score": 0,
        "fluff_score": 0,
        "technical_depth": 0,
        "novelty": 0,
        "relevance": 0,
        "summary": message,
        "why_selected": "Analysis failed.",
        "technically_sound_claims": [],
        "marketing_or_hype": [],
        "claims_to_verify": [message],
        "why_it_matters_to_me": [],
        "skeptical_take": "No useful judgment was produced because analysis failed.",
        "suggested_action": "Check the local model/runtime configuration.",
        "tags": ["analysis-error"],
        "analysis_error": message,
    }


def normalize_analysis(data: dict[str, Any], raw_output: str | None = None) -> dict[str, Any]:
    recommendation = str(data.get("recommendation", "watch")).strip().lower()
    if recommendation not in VALID_RECOMMENDATIONS:
        recommendation = "watch"

    normalized = {
        "recommendation": recommendation,
        "signal_score": clamp_score(data.get("signal_score")),
        "fluff_score": clamp_score(data.get("fluff_score")),
        "technical_depth": clamp_score(data.get("technical_depth")),
        "novelty": clamp_score(data.get("novelty")),
        "relevance": clamp_score(data.get("relevance")),
        "summary": str(data.get("summary", "")).strip(),
        "why_selected": str(data.get("why_selected", "")).strip(),
        "technically_sound_claims": ensure_string_list(data.get("technically_sound_claims")),
        "marketing_or_hype": ensure_string_list(data.get("marketing_or_hype")),
        "claims_to_verify": ensure_string_list(data.get("claims_to_verify")),
        "why_it_matters_to_me": ensure_string_list(data.get("why_it_matters_to_me")),
        "skeptical_take": str(data.get("skeptical_take", "")).strip(),
        "suggested_action": str(data.get("suggested_action", "")).strip(),
        "tags": ensure_string_list(data.get("tags")),
    }

    if raw_output and not normalized["summary"]:
        normalized["summary"] = strip_spinner_noise(raw_output)[:500]
    return normalized


def load_sources() -> dict[str, Any]:
    if not INPUT_FILE.exists():
        raise SystemExit(f"Input file not found: {INPUT_FILE}")
    with INPUT_FILE.open("r") as f:
        return json.load(f)


def analyze_article(topic: str, article: dict[str, Any]) -> dict[str, Any]:
    extracted = extract_article(str(article.get("url", "")), timeout=EXTRACT_TIMEOUT)
    article_title = str(article.get("title") or "Untitled")
    if extracted.title and (article_title == "Untitled" or article_title == str(article.get("url", ""))):
        article_title = extracted.title
    source_excerpt = str(article.get("content", ""))
    if extracted.ok:
        analysis_content = extracted.text
        content_source = "extracted_article_text"
    else:
        analysis_content = source_excerpt
        content_source = "search_excerpt_fallback"

    metadata = {
        "extracted_title": extracted.title,
        "site_name": extracted.site_name,
        "byline": extracted.byline,
        "published_date": extracted.published_date,
        "extracted_chars": extracted.content_chars,
        "extraction_error": extracted.error,
    }
    prompt = (
        ANALYSIS_PROMPT
        .replace("{topic}", str(topic))
        .replace("{title}", article_title)
        .replace("{url}", str(article.get("url", "")))
        .replace("{metadata}", json.dumps(metadata, indent=2))
        .replace("{content_source}", content_source)
        .replace("{extraction_status}", extracted.status)
        .replace("{content}", analysis_content)
    )
    analysis = analyze_with_ollama(prompt)
    return {**article, "title": article_title, "extraction": extracted.to_dict(), "content_source": content_source, "analysis": analysis}


def recommendation_rank(item: dict[str, Any]) -> tuple[int, int, int]:
    analysis = item["analysis"]
    order = {"read": 0, "skim": 1, "watch": 2, "ignore": 3}
    return (order.get(analysis["recommendation"], 3), -analysis["signal_score"], analysis["fluff_score"])


EMPTY_FIELD_VALUES = {
    "",
    "not specified.",
    "no skeptical take produced.",
    "no action suggested.",
    "none called out.",
}


def esc(value: Any) -> str:
    return html_lib.escape(str(value or ""), quote=True)


def meaningful(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    return text not in EMPTY_FIELD_VALUES


def html_list(items: list[str]) -> str:
    cleaned = [item for item in items if meaningful(item)]
    if not cleaned:
        return ""
    return "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in cleaned) + "</ul>"


def detail_section(title: str, items: list[str]) -> str:
    body = html_list(items)
    if not body:
        return ""
    return f"<div class=\"detail-group\"><h4>{esc(title)}</h4>{body}</div>"


def render_article_markdown(item: dict[str, Any]) -> list[str]:
    title = item.get("title", "Untitled")
    url = item.get("url", "")
    a = item["analysis"]
    recommendation = a["recommendation"].lower()
    extraction = item.get("extraction", {})
    tags = [tag for tag in a["tags"] if meaningful(tag)]
    tag_html = "".join(f"<span class=\"tag\">{esc(tag)}</span>" for tag in tags)
    error_html = ""
    if a.get("analysis_error"):
        error_html = f"<div class=\"analysis-error\">Analysis error: {esc(a['analysis_error'])}</div>"

    source = item.get("source") or extraction.get("site_name") or "unknown source"
    published = item.get("published") or extraction.get("published_date") or ""
    meta_bits = [esc(source), f"content: <code>{esc(item.get('content_source', 'unknown'))}</code>", f"extraction: <code>{esc(extraction.get('status', 'unknown'))}</code>"]
    if published:
        meta_bits.insert(1, esc(str(published)[:10]))

    detail_html = "".join(
        [
            detail_section("Technically sound claims", a["technically_sound_claims"]),
            detail_section("Marketing / hype / weak spots", a["marketing_or_hype"]),
            detail_section("Claims to verify", a["claims_to_verify"]),
            detail_section("Why it may matter to me", a["why_it_matters_to_me"]),
        ]
    )
    details = f"<details><summary>Details / claims</summary>{detail_html}</details>" if detail_html else ""

    summary = esc(a.get("summary", "")) if meaningful(a.get("summary")) else "No useful summary produced."
    skeptical_take = esc(a.get("skeptical_take", "")) if meaningful(a.get("skeptical_take")) else ""
    suggested_action = esc(a.get("suggested_action", "")) if meaningful(a.get("suggested_action")) else ""
    why_selected = esc(a.get("why_selected", "")) if meaningful(a.get("why_selected")) else ""

    lines = [
        f'<article class="article-card rec-{esc(recommendation)}">',
        '  <div class="article-header">',
        f'    <span class="badge badge-{esc(recommendation)}">{esc(recommendation.upper())}</span>',
        f'    <h2>{esc(title)}</h2>',
        '  </div>',
        f'  <div class="article-meta">{" · ".join(meta_bits)}</div>',
        f'  <div class="score-row"><span>Signal <b>{a["signal_score"]}</b></span><span>Fluff <b>{a["fluff_score"]}</b></span><span>Depth <b>{a["technical_depth"]}</b></span><span>Novelty <b>{a["novelty"]}</b></span><span>Relevance <b>{a["relevance"]}</b></span></div>',
        f'  <p class="summary">{summary}</p>',
    ]
    if skeptical_take:
        lines.append(f'  <p class="take"><strong>Skeptical take:</strong> {skeptical_take}</p>')
    if suggested_action:
        lines.append(f'  <p class="action"><strong>Suggested action:</strong> {suggested_action}</p>')
    if why_selected:
        lines.append(f'  <p class="why"><strong>Why selected:</strong> {why_selected}</p>')
    if tag_html:
        lines.append(f'  <div class="tags">{tag_html}</div>')
    if error_html:
        lines.append(f'  {error_html}')
    if details:
        lines.append(f'  {details}')
    if url:
        lines.append(f'  <p><a class="read-more" href="{esc(url)}">Read source →</a></p>')
    lines += ["</article>", ""]
    return lines


def render_digest_markdown(data: dict[str, Any], analyzed_articles: list[dict[str, Any]]) -> str:
    topic = data["topic"]
    ranked = sorted(analyzed_articles, key=recommendation_rank)
    kept = [item for item in ranked if item["analysis"]["recommendation"] != "ignore"]
    ignored = [item for item in ranked if item["analysis"]["recommendation"] == "ignore"]

    counts = {rec: sum(1 for item in ranked if item["analysis"]["recommendation"] == rec) for rec in ["read", "skim", "watch", "ignore"]}
    best = ranked[0] if ranked else None
    top_line = []
    if best:
        top_line = [
            '<div class="topline">',
            f'<strong>Today:</strong> {counts["read"]} read, {counts["skim"]} skim, {counts["watch"]} watch, {counts["ignore"]} ignore.',
            f'<br><strong>Best candidate:</strong> {esc(best.get("title", "Untitled"))}',
            '</div>',
            "",
        ]

    lines = [
        f"# 🔍 Topic: {topic}",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Model: `{OLLAMA_MODEL}`",
        f"Ollama timeout: `{OLLAMA_TIMEOUT}s`",
        "",
        "This digest is ranked for signal, relevance, technical substance, and low tolerance for vendor fluff.",
        "",
        *top_line,
    ]

    if kept:
        lines += ["# Worth attention", ""]
        for item in kept:
            lines += render_article_markdown(item)
    else:
        lines += ["# Worth attention", "", "No articles cleared the attention filter.", ""]

    if ignored:
        lines += ["# Rejected / low signal", ""]
        for item in ignored:
            lines += render_article_markdown(item)

    return "\n".join(lines)


def wrap_html(topic: str, digest_markdown: str) -> str:
    html = markdown2.markdown(digest_markdown, extras=["tables", "fenced-code-blocks"])
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{topic} Digest</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem auto; max-width: 1040px; line-height: 1.55; padding: 0 1rem 3rem; color: #1f2933; background: #f8fafc; }}
    h1 {{ border-bottom: 2px solid #e5e7eb; padding-bottom: .35rem; }}
    h2 {{ margin: 0; font-size: 1.18rem; line-height: 1.3; }}
    code {{ background: #eef2f7; padding: .1rem .25rem; border-radius: .25rem; }}
    a {{ color: #075985; }}
    strong {{ color: #111827; }}
    .topline {{ background: #0f172a; color: #f8fafc; padding: 1rem 1.2rem; border-radius: .8rem; margin: 1rem 0 1.5rem; }}
    .topline strong {{ color: #fff; }}
    .article-card {{ background: #fff; border: 1px solid #e5e7eb; border-left: 6px solid #94a3b8; border-radius: .85rem; padding: 1rem 1.15rem; margin: 1rem 0 1.25rem; box-shadow: 0 1px 2px rgba(15, 23, 42, .06); }}
    .article-card.rec-read {{ border-left-color: #16a34a; }}
    .article-card.rec-skim {{ border-left-color: #2563eb; }}
    .article-card.rec-watch {{ border-left-color: #d97706; }}
    .article-card.rec-ignore {{ border-left-color: #64748b; opacity: .88; }}
    .article-header {{ display: flex; align-items: flex-start; gap: .75rem; }}
    .badge {{ flex: 0 0 auto; display: inline-block; border-radius: 999px; padding: .25rem .55rem; font-size: .76rem; font-weight: 800; letter-spacing: .03em; color: #fff; }}
    .badge-read {{ background: #16a34a; }}
    .badge-skim {{ background: #2563eb; }}
    .badge-watch {{ background: #d97706; }}
    .badge-ignore {{ background: #64748b; }}
    .article-meta {{ color: #64748b; font-size: .9rem; margin: .45rem 0 .65rem; }}
    .score-row {{ display: flex; flex-wrap: wrap; gap: .4rem; margin: .5rem 0 .8rem; }}
    .score-row span {{ background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 999px; padding: .22rem .55rem; font-size: .88rem; }}
    .summary {{ font-size: 1rem; margin: .65rem 0; }}
    .take {{ background: #fff7ed; border-left: 4px solid #fb923c; padding: .55rem .7rem; border-radius: .35rem; }}
    .action {{ background: #ecfdf5; border-left: 4px solid #22c55e; padding: .55rem .7rem; border-radius: .35rem; }}
    .why {{ color: #475569; font-size: .94rem; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: .35rem; margin: .65rem 0; }}
    .tag {{ background: #e0f2fe; color: #075985; border-radius: 999px; padding: .18rem .45rem; font-size: .78rem; }}
    details {{ margin-top: .75rem; border-top: 1px solid #e5e7eb; padding-top: .55rem; }}
    summary {{ cursor: pointer; font-weight: 700; color: #334155; }}
    .detail-group h4 {{ margin: .75rem 0 .2rem; }}
    .detail-group ul {{ margin-top: .25rem; }}
    .read-more {{ display: inline-block; margin-top: .35rem; font-weight: 700; }}
    .analysis-error {{ background: #fef2f2; border: 1px solid #fecaca; color: #991b1b; padding: .55rem .7rem; border-radius: .45rem; }}
  </style>
</head>
<body>
{html}
</body>
</html>
"""


def save_analysis(data: dict[str, Any], analyzed_articles: list[dict[str, Any]]) -> None:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "topic": data["topic"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "model": OLLAMA_MODEL,
        "articles": analyzed_articles,
    }
    ANALYSIS_FILE.write_text(json.dumps(payload, indent=2))
    print(f"🧠 Analysis written to {ANALYSIS_FILE}")


def publish_digest(topic: str, digest: str) -> None:
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(digest)

    digest_files = sorted(glob.glob(str(DIGEST_DIR / "*_digest.md")))
    latest_digest = Path(digest_files[-1]) if digest_files else None

    print(f"✅ Digest written to {OUTPUT_FILE}")

    if latest_digest:
        NGINX_DIR.mkdir(parents=True, exist_ok=True)
        html_basename = OUTPUT_FILE.with_suffix(".html").name
        nginx_digest_path = NGINX_DIR / html_basename
        nginx_digest_path.write_text(wrap_html(topic, digest))

        index_path = NGINX_DIR / "index.html"
        if index_path.exists() or index_path.is_symlink():
            index_path.unlink()
        index_path.symlink_to(html_basename)
        print(f"🌐 HTML written to {nginx_digest_path}")
        print(f"🔗 index.html → {html_basename}")


def main() -> None:
    data = load_sources()
    topic = data["topic"]
    analyzed_articles = []
    for article in data["articles"]:
        print(f"Analyzing: {article.get('title', 'Untitled')}")
        analyzed_articles.append(analyze_article(topic, article))

    save_analysis(data, analyzed_articles)
    digest = render_digest_markdown(data, analyzed_articles)
    publish_digest(topic, digest)


if __name__ == "__main__":
    main()
