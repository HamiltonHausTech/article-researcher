#!/usr/bin/env python3
from __future__ import annotations

"""Best-effort article text extraction.

This intentionally avoids browser automation. It fetches normal HTML pages,
removes navigation/boilerplate, and extracts likely article text. If extraction
fails, callers can fall back to the search-generated excerpt in sources.json.
"""

import html
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
MAX_DOWNLOAD_BYTES = 2_000_000
MIN_EXTRACTED_CHARS = 700
MAX_ANALYSIS_CHARS = 18_000


@dataclass
class ExtractedArticle:
    url: str
    ok: bool
    text: str = ""
    title: str = ""
    site_name: str = ""
    byline: str = ""
    published_date: str = ""
    status: str = ""
    error: str = ""
    content_chars: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fetch_html(url: str, timeout: int = 20) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raw = raw[:MAX_DOWNLOAD_BYTES]
    charset = "utf-8"
    match = re.search(r"charset=([^;]+)", content_type, re.IGNORECASE)
    if match:
        charset = match.group(1).strip()
    return raw.decode(charset, errors="replace"), content_type


def meta_content(soup: BeautifulSoup, *selectors: str) -> str:
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            return clean_whitespace(str(tag["content"]))
        if tag and tag.get_text(strip=True):
            return clean_whitespace(tag.get_text(" ", strip=True))
    return ""


def clean_whitespace(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_boilerplate(soup: BeautifulSoup) -> None:
    for tag in soup([
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "iframe",
        "form",
        "nav",
        "header",
        "footer",
        "aside",
        "button",
    ]):
        tag.decompose()

    noisy_patterns = re.compile(
        r"(cookie|consent|subscribe|newsletter|signup|sign-up|social|share|related|advert|promo|modal|paywall|breadcrumb|comments)",
        re.IGNORECASE,
    )
    for tag in soup.find_all(True):
        attr_values = []
        for key in ("id", "class", "role", "aria-label"):
            if getattr(tag, "attrs", None) is None:
                continue
            raw_value = tag.get(key)
            if isinstance(raw_value, str):
                attr_values.append(raw_value)
            elif raw_value:
                attr_values.extend(str(item) for item in raw_value)
        values = " ".join(attr_values)
        if values and noisy_patterns.search(values):
            tag.decompose()


def candidate_score(tag: Any) -> int:
    text = clean_whitespace(tag.get_text("\n", strip=True))
    paragraphs = tag.find_all("p")
    headings = tag.find_all(["h1", "h2", "h3"])
    links = tag.find_all("a")
    text_len = len(text)
    para_text_len = sum(len(clean_whitespace(p.get_text(" ", strip=True))) for p in paragraphs)
    link_text_len = sum(len(clean_whitespace(a.get_text(" ", strip=True))) for a in links)
    score = text_len + para_text_len + len(paragraphs) * 80 + len(headings) * 40
    if text_len:
        score -= int((link_text_len / text_len) * 600)
    attrs = " ".join(str(tag.get(a, "")) for a in ("id", "class", "role"))
    if re.search(r"article|post|content|main|entry|story", attrs, re.IGNORECASE):
        score += 800
    if re.search(r"nav|menu|footer|header|sidebar|related", attrs, re.IGNORECASE):
        score -= 1000
    return score


def extract_main_text(soup: BeautifulSoup) -> str:
    preferred_selectors = [
        "article",
        "main article",
        "main",
        "[role='main']",
        ".post-content",
        ".entry-content",
        ".article-content",
        ".blog-post",
        ".content",
    ]

    candidates = []
    for selector in preferred_selectors:
        candidates.extend(soup.select(selector))
    if not candidates:
        candidates = soup.find_all(["article", "main", "section", "div"], limit=200)

    if not candidates:
        return clean_whitespace(soup.get_text("\n", strip=True))

    best = max(candidates, key=candidate_score)
    parts = []
    for tag in best.find_all(["h1", "h2", "h3", "p", "li", "blockquote", "pre"], recursive=True):
        piece = clean_whitespace(tag.get_text(" ", strip=True))
        if len(piece) < 20 and tag.name not in {"h1", "h2", "h3"}:
            continue
        parts.append(piece)

    if not parts:
        return clean_whitespace(best.get_text("\n", strip=True))

    deduped = []
    seen = set()
    for part in parts:
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(part)
    return clean_whitespace("\n\n".join(deduped))


def extract_article(url: str, timeout: int = 20) -> ExtractedArticle:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ExtractedArticle(url=url, ok=False, status="unsupported-url", error="Only http/https URLs are supported")

    try:
        raw_html, content_type = fetch_html(url, timeout=timeout)
    except urllib.error.HTTPError as e:
        return ExtractedArticle(url=url, ok=False, status="http-error", error=f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        return ExtractedArticle(url=url, ok=False, status="url-error", error=str(e.reason))
    except TimeoutError:
        return ExtractedArticle(url=url, ok=False, status="timeout", error=f"Timed out after {timeout}s")
    except Exception as e:  # noqa: BLE001 - extraction should fail soft
        return ExtractedArticle(url=url, ok=False, status="fetch-error", error=str(e))

    if "html" not in content_type.lower() and "xml" not in content_type.lower() and content_type:
        return ExtractedArticle(url=url, ok=False, status="non-html", error=f"Unsupported content type: {content_type}")

    soup = BeautifulSoup(raw_html, "html.parser")
    title = meta_content(soup, "meta[property='og:title']", "meta[name='twitter:title']", "title")
    site_name = meta_content(soup, "meta[property='og:site_name']") or parsed.netloc
    byline = meta_content(soup, "meta[name='author']", "[rel='author']")
    published_date = meta_content(
        soup,
        "meta[property='article:published_time']",
        "meta[name='date']",
        "meta[name='publish_date']",
        "time[datetime]",
    )

    remove_boilerplate(soup)
    text = extract_main_text(soup)
    text = clean_whitespace(text)
    if len(text) > MAX_ANALYSIS_CHARS:
        text = text[:MAX_ANALYSIS_CHARS].rsplit("\n", 1)[0].strip() + "\n\n[Truncated for analysis]"

    if len(text) < MIN_EXTRACTED_CHARS:
        return ExtractedArticle(
            url=url,
            ok=False,
            text=text,
            title=title,
            site_name=site_name,
            byline=byline,
            published_date=published_date,
            status="too-short",
            error=f"Extracted text too short ({len(text)} chars)",
            content_chars=len(text),
        )

    return ExtractedArticle(
        url=url,
        ok=True,
        text=text,
        title=title,
        site_name=site_name,
        byline=byline,
        published_date=published_date,
        status="ok",
        content_chars=len(text),
    )
