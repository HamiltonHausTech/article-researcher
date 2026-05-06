# Personal Article Digest

Small local article digest generator. It rotates through configured topics, finds recent article candidates using OpenAI web search, summarizes them with local Ollama, and publishes a simple HTML page suitable for serving from nginx.

This is currently a lightweight prototype. The next planned improvement is to replace generic summaries with skeptical article triage: read/skim/ignore recommendations, signal/fluff scores, claims to verify, and why an article may matter.

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

Install and run Ollama on the host, then pull the configured model:

```bash
ollama pull mistral
```

## Configuration

All paths are configurable by environment variable so the same checkout can run on a lab box, laptop, or container.

| Variable | Default | Purpose |
|---|---|---|
| `ARTICLES_DATA_DIR` | `~/ai-digests` | Base runtime data directory |
| `ARTICLES_TOPIC_FILE` | `$ARTICLES_DATA_DIR/topics.txt` | One topic per line |
| `ARTICLES_RECENT_FILE` | `$ARTICLES_DATA_DIR/recent.json` | Recently used topic history |
| `ARTICLES_RECENT_LIMIT` | `5` | Avoid repeating topics from last N runs |
| `ARTICLES_SOURCES_FILE` | `./sources.json` | Candidate article JSON between stages |
| `ARTICLES_DIGEST_DIR` | `$ARTICLES_DATA_DIR/daily` | Markdown digest output directory |
| `ARTICLES_NGINX_DIR` | `~/Projects/docker/nginx/html` | HTML publish directory |
| `ARTICLES_OPENAI_MODEL` | `gpt-4.1` | OpenAI model used for article discovery |
| `ARTICLES_FETCH_COUNT` | `4` | Number of candidate articles to request |
| `ARTICLES_OLLAMA_BIN` | `/usr/local/bin/ollama` | Ollama executable path |
| `ARTICLES_OLLAMA_MODEL` | `mistral` | Ollama model used for summary |

## Run

```bash
. .venv/bin/activate
python daily_digest.py
```

Or run the two stages manually:

```bash
python fetch_sources.py "AI and DevOps"
python summarize.py
```

## Lab box systemd example

Adjust paths for the lab box checkout and nginx directory.

`/etc/systemd/system/article-digest.service`:

```ini
[Unit]
Description=Personal article digest generator
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/home/andrew/Projects/hamiltonhaus/articles
Environment=ARTICLES_DATA_DIR=/home/andrew/ai-digests
Environment=ARTICLES_NGINX_DIR=/home/andrew/Projects/docker/nginx/html
Environment=ARTICLES_OLLAMA_BIN=/usr/local/bin/ollama
EnvironmentFile=-/home/andrew/Projects/hamiltonhaus/articles/.env
ExecStart=/home/andrew/Projects/hamiltonhaus/articles/.venv/bin/python /home/andrew/Projects/hamiltonhaus/articles/daily_digest.py
```

`/etc/systemd/system/article-digest.timer`:

```ini
[Unit]
Description=Run personal article digest daily

[Timer]
OnCalendar=*-*-* 06:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now article-digest.timer
systemctl list-timers article-digest.timer
```

## Current limitations

- `fetch_sources.py` currently relies on OpenAI web search returning article summaries/snippets; it does not yet fetch and analyze full article text.
- `summarize.py` still produces generic bullet summaries; the next improvement should add an article-judging JSON schema and richer HTML rendering.
- There is no dedupe/archive database yet.

## Quick validation

```bash
python3 -m compileall -q .
python summarize.py
```

The second command uses the existing `sources.json` and local Ollama. If Ollama is missing, the digest will contain an explicit error message instead of crashing.
