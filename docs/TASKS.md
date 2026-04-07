# Quarry — Task Breakdown & MVP

## MVP Definition

The MVP is a working end-to-end loop that:
1. Crawls a seeded list of companies (Greenhouse/Lever) on a schedule
2. Filters postings by embedding similarity to your ideal role
3. Delivers a daily digest
4. Lets you label postings via a minimal UI
5. Has an agent reflection step that can add/retire companies and queries

The MVP deliberately excludes: classifier training (day-1 there's no labeled data), Indeed API integration, generic careers page scraping, and the auto-retrain loop. Those are Phase 2.

---

## Phase 1 — MVP

### M1: Project scaffolding and database
**Goal:** Repo structure, config loading, SQLite schema, migrations.

Tasks:
- [ ] Create repo layout per README.md structure
- [ ] `config.py` — dataclass with all config fields; load from `config.yaml` + env var overrides
- [ ] `config.yaml.example` — document every field with comments
- [ ] `store/schema.sql` — full schema (companies, search_queries, postings, agent_log, classifier_runs)
- [ ] `store/db.py` — connection helper, `init()` migration runner, basic CRUD helpers
- [ ] `python -m store.db init` entrypoint

**Acceptance:** `python -m store.db init` creates a valid SQLite file with all tables.

---

### M2: Crawlers — JobSpy (broad discovery) + ATS endpoints (watchlist)
**Goal:** Reliably fetch structured job listings from both job boards and direct ATS endpoints.

**Prior art note:** `python-jobspy` is a well-maintained open source library that handles Indeed, Glassdoor, Google Jobs, ZipRecruiter, and LinkedIn scraping, returning structured `JobPost` objects. Use it for broad discovery. Do **not** build Indeed/Glassdoor/Google crawlers from scratch. The ATS endpoint crawlers (Greenhouse, Lever, Ashby) are still needed for the company watchlist use case and are not covered by JobSpy.

Tasks:
- [ ] `pip install python-jobspy` — validate it returns clean results for test searches
- [ ] `crawlers/jobspy_client.py` — thin wrapper around `scrape_jobs()` that maps `JobPost` → `RawPosting` dataclass and applies config (search terms, sites, results_wanted, hours_old)
- [ ] `crawlers/base.py` — `BaseCrawler` ABC with `fetch() -> list[RawPosting]` (for ATS crawlers)
- [ ] `crawlers/greenhouse.py` — GET `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`, parse JSON
- [ ] `crawlers/lever.py` — GET `https://api.lever.co/v0/postings/{slug}?mode=json`, parse JSON
- [ ] `crawlers/ashby.py` — POST `https://jobs.ashbyhq.com/api/non-user-graphql`, parse response
- [ ] `crawlers/careers_page.py` — httpx + BeautifulSoup fallback for companies not on major ATS
- [ ] `RawPosting` dataclass: title, company, url, description_html, location, remote, posted_at, source
- [ ] Rate limiting and retry with exponential backoff on ATS crawlers (use `tenacity`)
- [ ] Unit tests with fixture JSON for each ATS crawler; integration smoke test for JobSpy

**Also evaluate:** the `jobspy-mcp-server` community project. If it's stable, the agent could call JobSpy searches as MCP tool calls directly, eliminating the need for `jobspy_client.py` entirely.

**Acceptance:** `jobspy_client.py` returns correctly typed `RawPosting` objects for a test search. Each ATS crawler can fetch a known company's postings.

---

### M3: Extraction pipeline
**Goal:** Convert `RawPosting` HTML/text into clean structured `JobPosting` for storage.

Tasks:
- [ ] `pipeline/extract.py` — `extract(raw: RawPosting) -> JobPosting`
  - Strip HTML tags, normalize whitespace
  - Detect remote (keyword heuristics first, LLM fallback only if ambiguous)
  - Parse/normalize location string
- [ ] `JobPosting` dataclass (mirrors DB columns)
- [ ] Dedup check against DB before insert
- [ ] `store/db.py` — `insert_posting()`, `posting_exists(url)`

**Acceptance:** Given a `RawPosting` fixture, `extract()` returns a valid `JobPosting` with clean text and correct remote flag.

---

### M4: Embedding and similarity filter
**Goal:** Embed postings and score against the ideal role description.

Tasks:
- [ ] `pipeline/embedder.py` — `embed(text: str) -> np.ndarray`
  - Use `sentence-transformers` with `all-MiniLM-L6-v2` (local, no API cost, fast)
  - Alternatively wire to OpenAI embeddings via config flag
  - Cache embeddings in DB (serialize to BLOB)
- [ ] `pipeline/filter.py` — `score_similarity(posting, ideal_embedding) -> float`
  - Cosine similarity
  - Configurable threshold to mark posting as below-threshold (stored but not surfaced)
- [ ] On startup/first run: embed `config.ideal_role_description`, store in a `settings` table
- [ ] `pipeline/filter.py` — `apply_keyword_blocklist(posting) -> bool` (True = keep)

**Acceptance:** Given two postings (one clearly relevant, one not), scores are meaningfully different and threshold filtering works.

---

### M5: Agent tool loop and strategy reflection
**Goal:** Agent reads strategy state, processes recent results, and makes tool calls to update strategy.

Tasks:
- [ ] `agent/tools.py` — implement all tools from Architecture doc:
  - `get_strategy_summary()` — returns companies + queries + recent performance stats
  - `get_recent_results(n)` — recent postings with scores
  - `add_company(...)`, `retire_company(...)`, `update_company(...)`
  - `add_search_query(...)`, `retire_search_query(...)`
  - `log_observation(text)`
  - `trigger_retrain(reason)` — sets a flag in DB for Phase 2
- [ ] `agent/prompts.py` — system prompt for reflection run; includes strategy summary template
- [ ] `agent/agent.py` — `run_strategy_reflection()`:
  - Build context (strategy summary + recent results)
  - Call Claude API with tools
  - Execute tool calls in loop until `stop_reason == "end_turn"`
  - Log all tool calls with rationale to `agent_log`
- [ ] `agent/tools.py` — `seed()` entrypoint: populates initial companies and search queries from a YAML seed file
- [ ] `seed_data.yaml` — initial company list (20-30 companies, manually curated)

**Acceptance:** Running `python -m agent.agent --reflect` makes at least one sensible tool call and logs it to `agent_log`.

---

### M6: Scheduler
**Goal:** Automated daily search + weekly careers crawl + post-cycle reflection.

Tasks:
- [ ] `agent/scheduler.py` using APScheduler
  - `search_cycle()` — runs all active search queries through crawlers → extract → filter → insert
  - `careers_crawl()` — crawls all active companies' careers pages
  - `strategy_reflection()` — runs after each cycle with recent results context
- [ ] Each job logs start/end/count to `agent_log`
- [ ] `--run-once` flag for manual trigger
- [ ] Graceful shutdown handling

**Acceptance:** `python -m agent.scheduler --run-once` completes a full cycle without errors and populates the DB.

---

### M7: Daily digest
**Goal:** Ranked daily email/notification of new postings.

Tasks:
- [ ] `digest/digest.py` — `build_digest() -> DigestData`:
  - Fetch `new` postings from last 24h
  - Sort by `final_rank`
  - Group by company
  - Mark as `digest_included = True`
- [ ] `digest/notify.py` — `send_digest(data: DigestData)`:
  - Plain text format for stdout/email
  - Optional Slack webhook
  - Optional SMTP (use `config.notify_method`)
- [ ] Digest scheduled daily (configurable time)

**Acceptance:** `python -m digest.digest --send` outputs a ranked list of postings.

---

### M8: Labeling UI
**Goal:** Minimal web UI to label postings as interested / pass / applied.

Tasks:
- [ ] `ui/app.py` — Flask app, single-user, no auth
- [ ] Routes:
  - `GET /` — list of unread postings sorted by rank, paginated
  - `POST /label/<id>` — set status + user_label
  - `GET /companies` — view/edit company watchlist
  - `GET /log` — recent agent_log entries (read-only)
- [ ] Minimal HTML templates (no JS framework needed; plain HTML + a bit of CSS)
- [ ] Posting view: title, company, location, remote badge, similarity score, description (collapsible), link to original

**Acceptance:** Can view postings, label them, and see the label persist in DB.

---

## Phase 2 — Classifier and Feedback Loop

*Start once you have ~50 labeled postings (typically 2-4 weeks of use).*

### P2-1: Classifier training
- [ ] `pipeline/classifier.py` — `train(labeled_postings) -> ClassifierModel`
  - Logistic regression on embeddings (scikit-learn)
  - Cross-val AUC logged to `classifier_runs`
  - Save model to disk, mark active in DB
- [ ] `pipeline/classifier.py` — `score(posting, model) -> float`
- [ ] Wire classifier score into `final_rank` calculation
- [ ] `python -m pipeline.classifier train` manual trigger

### P2-2: Auto-retrain trigger
- [ ] After each label: check if N new labels since last train (configurable, default 20)
- [ ] If threshold met: queue retrain job
- [ ] Scheduler picks up queued retrain jobs

### P2-3: Classifier drift reflection
- [ ] After retrain: pass old vs new model feature weights to agent
- [ ] Agent proposes search query / company watchlist updates based on drift
- [ ] Prompt template: "The classifier up-weighted these features and down-weighted these. What does this suggest about how we should update our search strategy?"

---

## Phase 3 — Breadth expansion

### P3-1: Expand JobSpy source coverage
- [ ] Evaluate LinkedIn via JobSpy with proxy rotation (high value but rate-limited without proxies)
- [ ] Add Dice, Naukri, or other niche boards supported by JobSpy as relevant
- [ ] Tune `hours_old` and `results_wanted` per source based on signal/noise observed in practice

### P3-2: Generic careers page crawler (fallback)
- [ ] `crawlers/careers_page.py` — fetch HTML, use LLM to extract job listings
- [ ] Only used for companies not on Greenhouse/Lever/Ashby

### P3-3: Google Jobs search
- [ ] Use SerpAPI or similar to search `site:jobs.google.com` for target role keywords
- [ ] Extract and normalize results

---

## Phase 4 — Nice to haves

- [ ] Digest includes agent strategy notes ("Added 3 companies this week, retired 2 queries")
- [ ] Posting detail page with AI-generated fit summary ("This role matches your background in X but requires Y which you haven't done")
- [ ] Export labeled postings to CSV for external analysis
- [ ] Slack slash command to trigger a manual run
- [ ] Company detail page showing all postings seen over time (good for tracking company growth)

---

## Implementation Order (recommended)

```
M1 (schema) → M2 (JobSpy smoke test + ATS crawlers) → M3 (extraction) → M4 (embeddings)
     → M6 (scheduler, run-once) → M7 (digest) → M5 (agent reflection) → M8 (UI)
```

Get the data pipeline working first (M1-M4), then wire in the scheduler and digest so you're actually using it, then add the agent reflection layer. The UI is last because the digest is sufficient for daily use early on.

The JobSpy integration in M2 should take a few hours, not days — it's a `pip install` and a thin mapping layer. The ATS crawlers take longer but are the higher-signal source for your specific company watchlist.

---

## Dependencies

```
# Core
anthropic>=0.25.0
apscheduler>=3.10.0
flask>=3.0.0
requests>=2.31.0
tenacity>=8.2.0
pyyaml>=6.0
python-jobspy>=1.1.0      # broad discovery across job boards

# Embedding + ML
sentence-transformers>=2.7.0
scikit-learn>=1.4.0
numpy>=1.26.0

# Crawling
httpx>=0.27.0
beautifulsoup4>=4.12.0

# Utils
python-dotenv>=1.0.0
click>=8.1.0
pandas>=2.0.0             # JobSpy returns DataFrames
```

---

## Config fields (`config.yaml.example`)

```yaml
# === Core ===
db_path: ./jobhound.db
seed_file: ./seed_data.yaml

# === Role targeting ===
ideal_role_description: |
  Senior People Analytics or HR Technology leader role at a growth-stage
  tech company. Ideally involves building or leading a function, not just
  executing. Strong preference for companies doing interesting technical work.
  Open to Principal IC or Senior Manager scope.

keyword_blocklist:
  - "staffing agency"
  - "requires clearance"
  - "relocation required"

similarity_threshold: 0.58

# === Crawling ===
crawl_schedule_cron: "0 7 * * *"      # daily at 7am
careers_crawl_cron: "0 8 * * 1"       # weekly Monday 8am
reflection_after_crawl: true

# === Notifications ===
notify_method: stdout   # stdout | email | slack
digest_time: "08:30"

# SMTP (if notify_method = email)
smtp_host: smtp.gmail.com
smtp_port: 587
smtp_user: ""
smtp_password: ""
digest_recipient: ""

# Slack (if notify_method = slack)
slack_webhook_url: ""

# === Anthropic ===
anthropic_model: claude-sonnet-4-20250514
max_reflection_tokens: 2048

# === Embeddings ===
embedding_model: all-MiniLM-L6-v2    # local sentence-transformers model
# embedding_provider: openai          # uncomment to use OpenAI instead
# openai_api_key: ""

# === Classifier ===
retrain_label_threshold: 20           # retrain after this many new labels
model_dir: ./models/
```
