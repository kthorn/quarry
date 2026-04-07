# Quarry — Agentic Job Search System

An autonomous job search agent that discovers, filters, ranks, and tracks job postings — and continuously refines its own search strategy based on your feedback.

## What it does

- Crawls job boards (Indeed API, Greenhouse/Lever/Ashby ATS endpoints) and company careers pages on a schedule
- Maintains a self-updating database of target companies and search queries
- Filters postings via keyword blocklist → embedding similarity → trained classifier
- Surfaces a daily digest of ranked, relevant postings
- Learns from your feedback (applied / interested / pass) and retrains its classifier
- Reflects on classifier drift and proposes updates to its own search strategy

## Repository Structure

```
quarry/
├── __init__.py               # This file
├── ARCHITECTURE.md            # System design and data model
├── TASKS.md                   # Full task breakdown and MVP scope
├── agent/
│   ├── agent.py               # Main agent loop (tool loop + Claude API)
│   ├── tools.py               # All tool definitions (strategy R/W, search, crawl)
│   ├── prompts.py             # System prompt and reflection prompt templates
│   └── scheduler.py           # APScheduler jobs (daily search, weekly crawl, retrain trigger)
├── pipeline/
│   ├── extract.py             # HTML → structured JobPosting
│   ├── filter.py              # Keyword blocklist + embedding similarity
│   ├── classifier.py          # Train/load/apply sklearn classifier on embeddings
│   └── embedder.py            # Text → embedding (OpenAI or local sentence-transformers)
├── crawlers/
│   ├── base.py                # Base crawler interface
│   ├── jobspy_client.py       # JobSpy wrapper for broad discovery (Indeed, Glassdoor, Google Jobs, etc.)
│   ├── greenhouse.py          # Greenhouse ATS crawler (company watchlist)
│   ├── lever.py               # Lever ATS crawler (company watchlist)
│   ├── ashby.py               # Ashby ATS crawler (company watchlist)
│   └── careers_page.py        # Generic careers page crawler (fallback)
├── store/
│   ├── db.py                  # SQLite connection + migrations
│   └── schema.py              # Schema definition
├── digest/
│   ├── digest.py              # Build daily digest from ranked postings
│   └── notify.py              # Notification delivery (stdout)
├── ui/
│   └── app.py                 # Minimal Flask UI for labeling postings
├── config.py                  # Config dataclass (loaded from env / config.yaml)
├── config.yaml.example        # Example config
└── requirements.txt
```

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and edit config
cp config.yaml.example config.yaml

# 3. Initialize database
python -m quarry.store init

# 4. Seed initial companies and search queries
python -m quarry.agent.tools seed

# 5. Run a manual search cycle
python -m quarry.agent.agent --run-once

# 6. Start the scheduler (runs continuously)
python -m quarry.agent.scheduler

# 7. Start the labeling UI
python -m quarry.ui.app
```

## Key Design Decisions

See `ARCHITECTURE.md` for full rationale. Short version:

- **No heavy framework** — custom tool loop using the Anthropic Python SDK directly. The agent's job is well-defined enough that LangGraph/CrewAI overhead isn't worth it.
- **SQLite** — sufficient for one user, zero ops overhead, easy to inspect.
- **JobSpy for broad discovery** — `python-jobspy` handles Indeed, Glassdoor, Google Jobs, ZipRecruiter scraping out of the box. No need to build those crawlers from scratch.
- **Greenhouse/Lever/Ashby for watchlist** — direct ATS endpoint crawling for companies you specifically want to track. JobSpy doesn't cover these.
- **LinkedIn via JobSpy only** — works but rate-limits aggressively without proxies. Not a primary source.
- **Embedding similarity before classifier** — classifier needs labeled data to train; cosine sim against an "ideal role" description works on day 1 with zero training data.
- **Agent owns its strategy** — the agent reads and writes the `companies` and `search_queries` tables as explicit tool calls, with rationale logged per mutation.
