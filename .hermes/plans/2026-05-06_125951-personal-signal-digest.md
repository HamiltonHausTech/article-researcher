# Personal Signal Digest plan

## Goal

Evolve the existing article fetcher from a topic-rotating summary page into a personal technical intelligence filter:

- find recent/current articles from useful sources
- reject low-signal/vendor-fluff/SEO content before it reaches the front page
- produce skeptical, opinionated briefs tuned to Andrew's interests
- keep the local nginx digest workflow, but make the output decision-oriented
- support manual URL analysis for articles found elsewhere, such as TL;DR links

The target experience is: spend 5 minutes and know what is worth reading, what is mostly marketing, what claims need validation, and what might matter to current/future work.

## Current repo context

Path inspected: `/Users/andrewhamilton/Projects/hamiltonhaus/articles`

Files:

- `fetch_sources.py`
- `summarize.py`
- `daily_digest.py`
- `sources.json`

The repo is not currently a git repository.

The current live page at `http://192.168.0.156` shows a simple digest page titled `AI and Devops Digest` with a handful of article titles, read-more links, and bullet summaries.

## Current pipeline

Current intended flow:

1. `daily_digest.py`
   - loads topics from `~/ai-digests/topics.txt`
   - loads recent topic history from `~/ai-digests/recent.json`
   - randomly picks a topic not used recently
   - calls `fetch_sources.py`
   - calls `summarize.py`

2. `fetch_sources.py`
   - uses OpenAI `responses.create`
   - enables `web_search_preview`
   - asks GPT-4.1 to find recent high-quality technical articles for the topic
   - requests JSON array with `title`, `url`, and `content`
   - writes `sources.json`

3. `summarize.py`
   - reads `sources.json`
   - sends each article's already-summarized `content` to local Ollama model `mistral`
   - asks for 3-5 bullet points
   - writes markdown to `~/ai-digests/daily/<date>_digest.md`
   - converts markdown to HTML
   - copies latest HTML into `~/Projects/docker/nginx/html`
   - symlinks `index.html` to latest digest

## Important findings

### 1. The fetcher is not actually fetching article content

`fetch_sources.py` asks GPT-4.1 web search to return articles and a `content` field containing a 3-5 paragraph summary or excerpt.

That means the downstream summarizer is summarizing a search-model-generated summary, not the article itself.

This is likely the biggest reason the output feels generic. The system loses source-level evidence before analysis even begins.

### 2. There is no filtering/judgment stage

The current prompt says `recent, high-quality technical articles`, but there is no separate scoring or rejection pass.

Once GPT returns an item, it gets published.

There is no penalty for:

- vendor announcements
- sponsored content
- SEO explainers
- thin trend pieces
- duplicate/recycled stories
- old articles returned by mistake
- source quality problems
- lack of evidence
- weak relevance to Andrew's actual interests

### 3. The summaries are generic by design

`summarize.py` prompt:

```text
Summarize the following article in 3–5 bullet points
```

This cannot produce the kind of output Andrew is asking for, because it does not ask for:

- technical signal vs marketing
- what is new
- what is actionable
- what is speculative
- why it matters to him
- read/skim/ignore recommendation
- claims needing verification

### 4. The current model split may be counterproductive

Current setup:

- OpenAI GPT-4.1 performs article discovery and creates initial content snippets
- local Ollama `mistral` re-summarizes those snippets

For the desired output, the higher-capability model should probably do the judgment/analysis stage, at least initially. A small local model may be fine for simple bullets but is likely weak at nuanced hype-detection and technical triage.

### 5. There are portability/runtime issues in the inspected copy

Observed issues:

- No `requirements.txt` or dependency declaration.
- Current Python environment did not have `openai`, `dotenv`, or `markdown2` installed.
- `daily_digest.py` uses `script_dir = ~/Projects/python/articles`, but the inspected code is under `~/Projects/hamiltonhaus/articles`.
- `~/ai-digests/topics.txt` and `~/ai-digests/recent.json` were not present on this machine/session.
- `~/Projects/docker/nginx/html` was not present on this machine/session.
- `fetch_sources.py` and `summarize.py` use relative `sources.json`, so behavior depends on current working directory.
- The code compiles with `python3 -m compileall -q .`, but fresh runtime execution is not currently verifiable in this environment because dependencies/config paths are missing.

These may reflect that the real running service is on another host/container, but the repo should still be made less path-dependent.

## Desired product behavior

For each candidate article, the system should produce a structured article brief:

- title
- source
- URL
- date if available
- topics/tags
- recommendation: `read`, `skim`, `watch`, `ignore`
- signal score: 0-100
- fluff score: 0-100
- technical depth score: 0-100
- novelty score: 0-100
- relevance score: 0-100
- short plain-English summary
- technically sound claims
- marketing/hype/vendor-positioning language
- claims needing verification
- why this might matter to Andrew
- practical implications
- skeptical take
- suggested action

The page should sort by recommendation/signal score and ideally hide or collapse rejected items.

## Scoring rubric

Initial scoring dimensions:

- relevance to Andrew's interests: 0-20
- technical depth: 0-20
- novelty: 0-15
- evidence quality: 0-15
- practical usefulness: 0-15
- strategic/future relevance: 0-10
- source quality: 0-5

Penalties:

- vendor press release: -10 to -30
- generic AI trend piece: -20
- no concrete examples: -10
- duplicate/recycled story: -15
- thin summary of someone else's announcement: -10
- sponsored/ad-like content: -20
- SEO explainer with no new insight: -25
- stale article returned as recent: -15

Classification:

- 85-100: read
- 70-84: skim
- 55-69: maybe/watch
- below 55: ignore/collapse

## Proposed architecture

Keep the system simple and local-first, but split responsibilities clearly.

### `config/`

- `topics.txt` or `topics.yaml`
- `sources.yaml`
- `profile.yaml` describing Andrew's preferences/interests/scoring weights

### `data/`

- `articles.sqlite` or JSONL files for article metadata, raw text, analysis, and history
- `raw/` optional cached article text/HTML

### Pipeline modules

1. `discover.py`
   - finds candidate articles from topics/sources
   - can use RSS, TL;DR parsing, web search, or manual URL input

2. `extract.py`
   - fetches the actual URL
   - extracts readable article text
   - records extraction quality and failures

3. `analyze.py`
   - sends full extracted article text to LLM
   - returns strict JSON article analysis
   - includes recommendation/scores/skeptical take

4. `publish.py`
   - builds local HTML digest
   - ranks by recommendation and signal
   - includes collapsed rejected items

5. `daily_digest.py`
   - orchestrates the above steps

6. `analyze_url.py`
   - manual URL mode for ad hoc links from TL;DR, newsletters, chats, etc.

## Incremental implementation plan

### Phase 0: Stabilize current script paths and dependencies

Purpose: make the current system reproducible before improving behavior.

Tasks:

- Add `requirements.txt` with at least:
  - `openai`
  - `python-dotenv`
  - `markdown2`
  - likely `requests`, `beautifulsoup4`, `readability-lxml` or similar later
- Make script directory dynamic in `daily_digest.py` using `Path(__file__).parent` instead of hardcoded `~/Projects/python/articles`.
- Make `sources.json` path relative to script directory or a configured data directory.
- Move paths into config/env vars:
  - topics file
  - recent file
  - digest output dir
  - nginx html dir
  - Ollama model
- Add a `README.md` with the current run command and expected paths.

Validation:

- `python3 -m compileall -q .`
- `python3 daily_digest.py` with a small test topic file
- confirm HTML appears where expected

### Phase 1: Add article judging without changing discovery

Purpose: smallest useful improvement.

Keep `fetch_sources.py` as-is for discovery, but replace the generic Ollama summarization prompt with a structured analysis prompt.

Output strict JSON for each article:

```json
{
  "recommendation": "read|skim|watch|ignore",
  "signal_score": 0,
  "fluff_score": 0,
  "technical_depth": 0,
  "novelty": 0,
  "relevance": 0,
  "summary": "...",
  "technically_sound_claims": [],
  "marketing_or_hype": [],
  "claims_to_verify": [],
  "why_it_matters_to_me": [],
  "skeptical_take": "...",
  "tags": []
}
```

Change HTML output to show:

- recommendation badge
- signal/fluff scores
- skeptical take
- key claims
- why it matters

This gives immediate value even before full article extraction exists.

Validation:

- Run against existing `sources.json`.
- Confirm Fivetran-style article would be classified as `skim` with medium/high fluff.
- Confirm Subquadratic-style article would be classified as `watch` or `skim`, high potential but high verification need.

### Phase 2: Fetch and analyze actual article text

Purpose: stop summarizing summaries.

Tasks:

- Add `extract.py` using a readable-content extractor.
- Store article metadata and extracted text.
- Pass extracted article text to the analysis prompt.
- Detect and flag extraction failures/truncated pages.
- Keep the search-returned snippet as fallback only.

Validation:

- Run manual extraction on:
  - Fivetran ODI article
  - The New Stack Subquadratic article
  - a known vendor launch post
  - a thin SEO/listicle article
- Confirm analysis uses actual article content and cites concrete claims from it.

### Phase 3: Add manual URL analysis

Purpose: support the real workflow Andrew described.

Add command:

```bash
python3 analyze_url.py https://example.com/article
```

Behavior:

- fetch URL
- extract article
- analyze with same rubric
- write result into archive
- optionally publish/update a `manual-review.html` page or include in current digest

Validation:

- Run with TL;DR-linked articles.
- Confirm output matches the type of analysis desired in chat: real vs hype, verification needs, practical implication.

### Phase 4: Improve discovery sources

Purpose: better candidates in, better digest out.

Add source types:

- RSS feeds
- TL;DR email/newsletter parsing if available locally
- manual URL queue
- web search as fallback

Possible source config:

```yaml
sources:
  - name: The New Stack
    type: rss
    url: https://thenewstack.io/feed/
    topics: [ai, devops, infrastructure]
  - name: TLDR AI
    type: newsletter
    mailbox_or_file: TBD
  - name: OpenAI Blog
    type: rss
    url: https://openai.com/news/rss.xml
    vendor: true
```

Vendor sources are allowed, but scored harshly unless the article has concrete technical substance.

### Phase 5: Add feedback loop

Purpose: tune to Andrew without requiring prompt-writing every day.

Add lightweight controls to local page or a CLI:

- more like this
- less like this
- vendor fluff
- not relevant
- save
- follow up

Store feedback and inject into future analysis/scoring prompt.

Do not overbuild this first. A JSONL file of feedback is enough.

## Suggested first code change

The highest-leverage first change is NOT better source discovery. It is adding a judgment layer.

Start with current `sources.json` and replace `summarize.py`'s generic bullet prompt with an `analyze_article()` function that returns structured JSON and renders a richer page.

Why this first:

- small surface area
- preserves current daily job
- immediately addresses the main pain: generic summaries and weak filtering
- creates the schema needed for future extraction, source expansion, and feedback

## Suggested analysis prompt

System/task prompt:

```text
You are a skeptical technical analyst filtering articles for a senior DevOps/platform engineer.

The user is interested in practical infrastructure, AWS, Kubernetes, Terraform, DevOps/platform engineering, AI agents/tools, local/private AI, data infrastructure, security/ops risk, and useful emerging technology.

The user has limited time and dislikes vendor fluff, generic trend pieces, SEO explainers, recycled content, and ungrounded hype.

Analyze the article candidate below. Decide whether it is worth the user's attention. Separate technically meaningful claims from marketing language. Penalize thin vendor announcements and generic trend content. Prefer concrete technical details, independent evidence, operational lessons, architecture, benchmarks, failure modes, and practical implications.

Return strict JSON only.
```

User payload:

```text
Topic: {topic}
Title: {title}
URL: {url}
Source/date if known: {metadata}
Article text or excerpt:
{content}

Return JSON with:
- recommendation: read|skim|watch|ignore
- signal_score: 0-100
- fluff_score: 0-100
- technical_depth: 0-100
- novelty: 0-100
- relevance: 0-100
- summary: concise paragraph
- technically_sound_claims: array of strings
- marketing_or_hype: array of strings
- claims_to_verify: array of strings
- why_it_matters_to_me: array of strings
- skeptical_take: concise paragraph
- tags: array of strings
```

## Risks and tradeoffs

- Better analysis may cost more if done with a strong hosted model.
- Local models may be cheaper but weaker at nuanced technical skepticism.
- Full article extraction will fail on some sites; the system should flag extraction quality rather than silently summarize garbage.
- Too many scores can become noise; the page should show only the useful ones.
- Personalization should remain simple at first; avoid building a recommendation engine before the basic triage loop works.

## Definition of done for the first useful milestone

Given the existing daily workflow, the digest page should show 3-5 candidates with:

- read/skim/watch/ignore recommendation
- signal score
- fluff score
- skeptical take
- technically sound claims
- claims needing verification
- why it might matter to Andrew

Articles below a configured threshold should be collapsed or placed in a `Rejected / low signal` section.

The system should be able to run against the existing `sources.json` without changing discovery.

## Open questions

- Is the running version actually this repo, or a copy under another path/container?
- Is the digest host at `192.168.0.156` local to another machine/container with different paths?
- Should strong hosted models be allowed for analysis, or should the system stay local/Ollama-first?
- Where does TL;DR arrive: email, RSS, web page, or manual links only?
- Should the daily digest remain one rotating topic, or should it produce a cross-topic ranked briefing?
- Should ignored articles be stored for debugging, or discarded?
