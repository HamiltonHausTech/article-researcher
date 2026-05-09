# Personal Article Digest

Small local article digest generator. It rotates through configured topics, finds recent article candidates from curated feeds or OpenAI web search, analyzes them with local Ollama, and publishes a decision-oriented HTML page suitable for serving from nginx.

This is currently a lightweight prototype. The summarizer now performs skeptical article triage: read/skim/watch/ignore recommendations, signal/fluff scores, claims to verify, and why an article may matter.

## Fresh setup

```bash
cd ~/Projects/hamiltonhaus/articles
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp topics.example.txt ~/ai-digests/topics.txt
```

Create `.env` with your OpenAI key, or export it in the shell/service environment:

```bash
OPENAI_API_KEY=...
```

Install and run Ollama on the host, then pull the configured model. The current default is `qwen2.5:7b-instruct`, which is a stronger local default than the older `mistral` model for structured technical triage:

```bash
ollama pull qwen2.5:7b-instruct
```

Other local options to consider:

- `qwen2.5:7b-instruct`: good default balance of quality, speed, and JSON-following.
- `llama3.2:3b`: faster/lighter, but weaker for nuanced hype detection.
- `gpt-oss:latest`: available locally on this machine and potentially stronger, but slower and more verbose/reasoning-heavy in quick tests.

Set `ARTICLES_OLLAMA_MODEL` if you want to try a different model without editing source.

## Configuration

All paths are configurable by environment variable so the same checkout can run on a lab box, laptop, or container.

| Variable | Default | Purpose |
|---|---|---|
| `ARTICLES_DATA_DIR` | `~/ai-digests` | Base runtime data directory |
| `ARTICLES_TOPIC_FILE` | `$ARTICLES_DATA_DIR/topics.txt` | One topic per line |
| `ARTICLES_RECENT_FILE` | `$ARTICLES_DATA_DIR/recent.json` | Recently used topic history |
| `ARTICLES_RECENT_LIMIT` | `5` | Avoid repeating topics from last N runs |
| `ARTICLES_SOURCES_FILE` | `./sources.json` | Candidate article JSON between stages |
| `ARTICLES_DISCOVERY_MODE` | `feeds` | Daily discovery mode: `feeds` or `search` |
| `ARTICLES_FEEDS_FILE` | `./source_feeds.json` | Curated RSS/Atom source list |
| `ARTICLES_SEEN_FILE` | `$ARTICLES_DATA_DIR/seen_urls.json` | URL archive used to suppress repeats |
| `ARTICLES_FEED_LIMIT` | `$ARTICLES_FETCH_COUNT` or `6` | Number of feed candidates to keep |
| `ARTICLES_FEED_DAYS` | `14` | Feed item recency window |
| `ARTICLES_MAX_PER_FEED` | `2` | Per-source cap before backfilling, to avoid one feed dominating |
| `ARTICLES_DIGEST_DIR` | `$ARTICLES_DATA_DIR/daily` | Markdown digest output directory |
| `ARTICLES_NGINX_DIR` | `~/Projects/docker/nginx/html` | HTML publish directory |
| `ARTICLES_OPENAI_MODEL` | `gpt-4.1` | OpenAI model used for article discovery |
| `ARTICLES_FETCH_COUNT` | `4` | Number of candidate articles to request |
| `ARTICLES_OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama API endpoint |
| `ARTICLES_OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Ollama model used for article triage |
| `ARTICLES_OLLAMA_TIMEOUT` | `300` | Seconds to allow each local-model analysis request |
| `ARTICLES_EXTRACT_TIMEOUT` | `20` | Seconds to spend fetching each article URL |
| `ARTICLES_MAX_ANALYSIS_CHARS` | `18000` | Max extracted article characters sent to the local model |

## Run

```bash
. .venv/bin/activate
python daily_digest.py
```

Or run the two stages manually:

```bash
python feed_fetch.py "AI and DevOps"
python summarize.py
```

Use OpenAI web search discovery instead of curated feeds:

```bash
ARTICLES_DISCOVERY_MODE=search python daily_digest.py
# or manually:
python fetch_sources.py "AI and DevOps"
python summarize.py
```

Analyze a manually supplied article URL without running the daily topic rotation:

```bash
python analyze_url.py "https://www.fivetran.com/blog/what-is-open-data-infrastructure"
```

Manual URL analysis writes a markdown digest and JSON analysis under `$ARTICLES_DATA_DIR`. Add `--publish` to also write an HTML copy into `$ARTICLES_NGINX_DIR` without replacing the daily `index.html`:

```bash
python analyze_url.py --topic "data infrastructure" --publish "https://www.fivetran.com/blog/what-is-open-data-infrastructure"
```

Output behavior:

- Markdown archives are written under `$ARTICLES_DIGEST_DIR` / `$ARTICLES_DATA_DIR/daily`.
- Structured JSON analysis is written under `$ARTICLES_ANALYSIS_DIR` / `$ARTICLES_DATA_DIR/analysis`.
- The daily digest writes real `.html` files into `$ARTICLES_NGINX_DIR` and updates `$ARTICLES_NGINX_DIR/index.html` to point at the latest daily HTML file.
- Manual `analyze_url.py --publish` writes an HTML file into `$ARTICLES_NGINX_DIR`, but does not replace `index.html`.

## Lab box systemd timer

Prefer a user-level systemd timer for the lab box. The checkout, data directory,
`.env`, and nginx publish directory all live under the owning user's home
directory, so running the digest as that same user avoids brittle permissions or
home-directory traversal problems from a system service user.

If an older system-level timer is already installed, disable it first so it
doesn't keep running the broken unit:

```bash
sudo systemctl disable --now article-digest.timer 2>/dev/null || true
```

Install the provided user units:

```bash
cd ~/Projects/hamiltonhaus/articles
./scripts/install-user-timer.sh
```

Validate:

```bash
systemctl --user list-timers article-digest.timer
systemctl --user start article-digest.service
journalctl --user -u article-digest.service -n 100 --no-pager
```

If the timer should run after boot without an active login session, enable user
lingering once on the lab box:

```bash
sudo loginctl enable-linger "$USER"
```

The installed units come from:

- `systemd/article-digest.service`
- `systemd/article-digest.timer`

They use `%h` systemd specifiers, so the same files work for `/home/andrew`, a
renamed account, or another lab host without hard-coding the home directory.

If you intentionally install this as a system unit under `/etc/systemd/system`,
make sure the service runs as a user that can traverse and read every path it
uses, or move the checkout/runtime files to a service-owned path such as
`/opt/article-digest` and keep writable data under `/var/lib/article-digest`.

## Current limitations

- `feed_fetch.py` is the default deterministic discovery path. `fetch_sources.py` remains available as OpenAI web search fallback/exploration.
- Article extraction is best-effort static HTML extraction. Sites that block bots, require JavaScript, or serve paywalls fall back to the search excerpt.
- Feed discovery dedupes normalized URLs and tracks selected URLs in `$ARTICLES_SEEN_FILE`, but there is not yet a full feedback database for post-analysis ratings.

## Quick validation

```bash
python3 -m compileall -q .
python summarize.py
```

The second command uses the existing `sources.json` and local Ollama. If Ollama is missing, the digest will contain an explicit error message instead of crashing.
