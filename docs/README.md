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
├── agent/
│   ├── __main__.py          # CLI: run-once, seed, recompute-similarity
│   ├── scheduler.py         # run_once() — one crawl cycle (crawl → ingest filter → embed → rank)
│   └── tools.py             # CLI: seed, backfill-descriptions, normalize-locations, recompute-similarity
├── crawlers/
│   ├── base.py              # Base crawler interface
│   ├── jobspy_client.py     # JobSpy wrapper for broad discovery (Indeed, Glassdoor, Google Jobs, etc.)
│   ├── greenhouse.py / lever.py / ashby.py   # ATS crawlers for watchlist companies
│   └── careers_page.py      # Generic careers page crawler (fallback)
├── pipeline/
│   ├── extract.py           # HTML → structured JobPosting
│   ├── filter.py            # Ingest filter pipeline + read-time evaluate_location_match
│   ├── embedder.py          # Text → embedding (sentence-transformers)
│   ├── locations.py         # Location parsing + geocoding (geonamescache)
│   └── search.py            # Search-query crawl orchestration
├── rank/
│   ├── pipeline.py          # Ranking pipeline (similarity + classifier + fit aggregation)
│   ├── train.py             # Train sklearn classifier on labels; _MODELS_DIR for .pkl artifacts
│   ├── scorers/             # Individual scoring components (similarity, classifier, fit, …)
│   ├── config.py / context.py / registry.py / aggregation.py
├── resolve/
│   ├── pipeline.py          # Company domain/careers-URL/ATS resolution pipeline
│   ├── ats_detector.py / domain_resolver.py / careers_resolver.py / description.py
├── store/
│   ├── __main__.py          # CLI: init, add-company, reset
│   ├── db.py                # SQLite Database class + all CRUD/query methods
│   ├── models.py            # SQLAlchemy ORM models (all tables)
│   ├── schema.py            # Schema definition
│   └── session.py           # Engine + session factory
├── digest/
│   └── digest.py            # Daily digest builder (file output)
├── ui/
│   ├── __main__.py          # CLI: run the labeling UI
│   ├── app.py / routes.py   # Flask app + routes (/postings, /settings, /companies, …)
│   └── templates/ static/   # Jinja templates + CSS
├── config.py                # Pydantic Settings (config.yaml + env var overrides)
├── settings_service.py      # Per-user settings service (typed, DB-backed with config.yaml fallback)
├── models.py                # Pydantic data models (JobPosting, Company, FilterDecision, …)
├── llm.py / http.py         # LLM + HTTP helpers (Bedrock / OpenRouter)
├── models/                  # Trained classifier .pkl artifacts
├── config.yaml.example      # Example config (copy to config.yaml)
└── requirements.txt
```

## Quickstart

```bash
# 1. Install (CPU-only torch; the -c constraints.txt is REQUIRED to avoid ~2GB CUDA deps)
pip install -e ".[dev]" -c constraints.txt

# 2. Copy and edit config
cp config.yaml.example config.yaml

# 3. Initialize the database
python -m quarry.store init

# 4. Seed initial companies (from seed_data.yaml)
python -m quarry.agent.tools seed

# 5. Run a crawl cycle (crawl → ingest filter → embed → rank)
python -m quarry.agent run-once

# 6. Start the labeling UI
python -m quarry.ui
```

## CLI Reference

All commands are Click subcommands grouped by module. Run any with `--help` for full options.

### `python -m quarry.store` — database management

| Command | Description |
|---|---|
| `init` | Initialize the database with schema (creates `quarry.db`). |
| `add-company --name NAME [--domain DOMAIN] [--careers-url URL]` | Add a company and resolve its ATS type. |
| `reset [--keep-companies] [--yes]` | Reset the database. `--keep-companies` preserves companies, watchlist, search queries, settings, users, pipeline_configs, locations; deletes postings, labels, classifier versions, crawl_runs, and `.pkl` models. Full mode drops everything and re-seeds the default user. `--yes` skips the confirmation prompt. |

### `python -m quarry.agent` — crawl & agent commands

| Command | Description |
|---|---|
| `run-once` | Run a single crawl cycle (crawls companies + search queries, ingest-filters, embeds, ranks). Emits an `Ingest filter summary:` line at the end. |
| `seed` | Load seed companies from `seed_data.yaml`. |
| `recompute-similarity` | Recompute all similarity scores against the current ideal-role embedding. |

### `python -m quarry.agent.tools` — maintenance tools

| Command | Description |
|---|---|
| `seed [--seed-file PATH]` | Seed companies from YAML (default `./seed_data.yaml`). |
| `backfill-descriptions [--backfill-all]` | Generate descriptions for companies missing one. |
| `normalize-locations [--dry-run]` | Parse and normalize location data for all existing postings. |
| `recompute-similarity` | Recompute all similarity scores against the current ideal-role embedding. |

### `python -m quarry.ui` — labeling UI

| Command | Description |
|---|---|
| `python -m quarry.ui [--host HOST] [--port PORT] [--debug]` | Run the Flask labeling UI (postings feed, labeling, settings, companies). Defaults from `config.yaml`. |

### Typical reset + re-crawl sequence

```bash
# Clean restart keeping company infrastructure (recommended after config/filter changes)
python -m quarry.store reset --keep-companies --yes
python -m quarry.agent run-once       # re-crawl to repopulate postings
# Then re-label from the UI (http://localhost:<port>/postings); retrain once you have ≥5 labels.

# Full wipe + re-seed (starting over)
python -m quarry.store reset --yes
python -m quarry.agent.tools seed
python -m quarry.agent run-once
```

## Verification

```bash
python -m pytest                           # Run all tests
ruff check .                               # Lint (auto-fix: --fix)
PYTHONPATH=. pyright quarry/                # Type check
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
