# STATUS

Last updated: 2026-04-29

## Phase 1 — MVP Progress

| Milestone                                 | Status                 | Completed Plan |
| ----------------------------------------- | ---------------------- | -------------- |
| M1: Project scaffolding & database        | **DONE**               | 2026-04-05     |
| M2: Crawlers (JobSpy + ATS endpoints)     | **DONE**               | 2026-04-06     |
| M3: Extraction pipeline                   | **DONE**               | 2026-04-07     |
| M4: Embedding & similarity filter         | **DONE**               | 2026-04-09     |
| M5: Agent tool loop & strategy reflection | **NOT STARTED**        | —              |
| M6: Scheduler (run-once)                  | **DONE** (minimal)     | 2026-04-10     |
| M7: Daily digest                          | **DONE** (file output) | 2026-04-10     |
| M8: Labeling UI                           | **DONE**               | 2026-04-14     |

## Additional Work (Beyond TASKS.md)

- **Seed data**: 29 AI/robotics companies in `seed_data.yaml` with `python -m quarry.agent.tools seed`
- **Company resolver pipeline** (`quarry/resolve/`): domain resolution, careers URL detection, ATS type detection, `add-company` CLI command
- **Location filter design spec**: added to docs
- **Location normalization**: structured location parsing with `quarry/pipeline/locations.py`, `work_model` replacing `remote` boolean, `locations` + `job_posting_locations` tables, geonamescache-based resolution, location filtering in pipeline
- **Unified filter pipeline**: `FilterStep` protocol with `KeywordBlocklistFilter`, `TitleKeywordFilter`, `CompanyFilter`, `LocationFilter` classes; `FiltersConfig` Pydantic models with typed config; similarity as soft gate (threshold applied at read time, not write time); `recompute-similarity` CLI command
- **Title keyword filter**: positive-match filter requiring at least one keyword in the job title; configured via `filters.title_keyword.keywords`; rejects postings with no matching keyword (skip_reason: `title_keyword`); placed early in pipeline to avoid embedding compute on irrelevant postings from ATS board crawlers
- **Location filter: haversine distance matching**: `nearby_radius` config resolves target locations to lat/lon and accepts postings within radius; Oakland (12mi from SF) passes with 50mi radius, LA fails
- **Location filter: accept_states / accept_regions**: broader geographic filters; postings with only a state or region code (no city) can pass when these are configured
- **Location filter work_model fix**: `LocationFilter` now uses `posting.work_model` (authoritative post-extraction value) instead of `parse_result.work_model`; `accept_remote=True` now also passes postings with `work_model=None` (unknown work model treated as potentially remote)
- **Search CLI** (`python -m quarry.pipeline search`): keyword filtering by title/description, similarity scoring against an ad-hoc ideal description, terminal table output via tabulate
- **Crawl log CSV**: ATS crawler 404 handling, noisy log suppression
- **RUNBOOK.md**: pre-execution checklist and operational guide

## Completed Plans

All refined plans in `docs/plans/completed/`:

1. `2026-04-05-m1-project-scaffolding.md`
2. `2026-04-06-m2-crawlers-implementation.md`
3. `2026-04-07-extraction-pipeline.md`
4. `2026-04-09-m4-embedding-similarity.md`
5. `2026-04-10-scheduler-and-digest-minimal.md`
6. `2026-04-10-seed-data.md`
7. `2026-04-11-company-resolver.md`
8. `2026-04-12-location-normalization.md`
9. `2026-04-11-company-resolver.md`
10. `2026-04-12-haversine-location-matching-design.md`
11. `2026-04-12-unified-filter-pipeline.md`
12. `2026-04-14-m8-labeling-ui.md`
13. **`2026-04-29-multi-user-schema.md`** (Phase 1 of 4: DDL) — schema rewritten with per-user tables; 28 schema tests passing; old `quarry.db` replaced; schema documentation at `docs/multi-user-schema.md`

## Verification

- `python -m quarry.store init` — initializes database
- `python -m quarry.agent.tools seed` — loads seed companies
- `python -m quarry.agent run-once` — single search cycle (mocked crawlers work; live crawlers need API keys)
- `python -m quarry.digest` — writes ranked digest file
- `python -m quarry.agent.tools normalize-locations` — parse and normalize location data for existing postings
- `python -m quarry.agent recompute-similarity` — recompute all similarity scores
- `python -m quarry.ui` — labeling UI (Flask)
- `python -m pytest tests/test_db.py -v` — **28 schema tests passing** (all green)
- `python -m pytest tests/test_orm.py -v` — **17 ORM tests passing** (Phase 2)
- `ruff check .` — clean
- `pyright quarry/store/models.py quarry/store/session.py quarry/store/db.py tests/test_orm.py` — clean
- **Note:** CRUD-dependent tests (test_ui.py, test_seed.py, test_m4_integration.py, etc.) are broken pending Phase 3 CRUD rewrite. The `db.py` raw-SQL methods still target pre-Phase-1 schema.

## Remaining MVP Tasks (from TASKS.md)

### M5: Agent tool loop & strategy reflection (NOT STARTED)

- [ ] `agent/tools.py` — `get_strategy_summary()`, `get_recent_results(n)`, `retire_company()`, `update_company()`, `add_search_query()`, `retire_search_query()`, `log_observation()`, `trigger_retrain()`
- [ ] `agent/prompts.py` — system prompt for reflection run with strategy summary template
- [ ] `agent/agent.py` — `run_strategy_reflection()`: build context, call LLM with tools, execute tool calls in loop, log to `agent_log`
- [x] `agent/tools.py` — `seed()` entrypoint (DONE)
- [x] `seed_data.yaml` — initial company list (DONE, 29 companies)

### M6: Scheduler enhancements (partial — run-once works)

- [ ] APScheduler integration (`search_cycle`, `careers_crawl`, `strategy_reflection` jobs)
- [ ] Log start/end/count to `agent_log` for each scheduled job
- [ ] Graceful shutdown handling

### M7: Daily digest enhancements (partial — file output works)

- [ ] `send_digest()` — email (SMTP) and Slack webhook delivery
- [ ] Digest scheduled daily (configurable time)

### M8: Labeling UI (DONE)

- [x] `ui/app.py` — Flask app factory (`create_app()`), single-user, no auth
- [x] `GET /` — redirects to `/postings`
- [x] `GET /postings` — list postings sorted by similarity, paginated, with status filter tabs (new/seen/applied/rejected/archived)
- [x] `POST /label/<id>` — set status + create Label record
- [x] `GET /companies` — view company watchlist with active/inactive toggle
- [x] `GET /log` — recent agent_actions entries (read-only)
- [x] HTML templates (Jinja2 + CSS, no JS framework): base, postings, companies, log
- [x] Posting view: title, company, location, work_model badge, similarity score, description (collapsible), original link
- [x] `python -m quarry.ui` CLI entrypoint with `--host`, `--port`, `--debug`
- [x] DB helpers: `get_posting_by_id`, `update_posting_status`, `count_postings`, `get_postings_paginated`, `get_labels_for_posting`, `get_agent_actions`

### Beyond MVP

- Deploy to EC2 (systemd service, reverse proxy, TLS)
- P2-1: Classifier training (logistic regression on embeddings, after ~50 labels)
- P2-2: Auto-retrain trigger
- P2-3: Classifier drift reflection
- P3: Breadth expansion (LinkedIn/proxies, generic careers page, Google Jobs)

## Multi-User Architecture (Phased)

| Phase                                 | Status      | Document                                                       |
| ------------------------------------- | ----------- | -------------------------------------------------------------- |
| Phase 1: DDL schema                   | **DONE**    | `docs/superpowers/plans/2026-04-29-multi-user-schema.md`       |
| Phase 2: SQLAlchemy 2.0 ORM + Alembic | Not started | `docs/superpowers/plans/2026-04-29-multi-user-architecture.md` |
| Phase 3: CRUD rewrite                 | Not started | `docs/superpowers/plans/2026-04-29-multi-user-architecture.md` |
| Phase 4: Caller updates               | Not started | `docs/superpowers/plans/2026-04-29-multi-user-architecture.md` |

Schema documentation: `docs/multi-user-schema.md` (includes ERD)

## Key Files

```
quarry/
├── agent/          scheduler, tools (seed, recompute-similarity, add-company, normalize-locations), CLI
├── crawlers/       greenhouse, lever, ashby, careers_page, jobspy_client
├── digest/         build + write digest file
├── pipeline/       extract, embedder, filter (FilterStep classes), locations, search
├── resolve/        company resolver (domain, ATS detection)
├── store/          db.py, schema.py
├── config.py       Settings (Pydantic + YAML), FiltersConfig models
├── models.py       Pydantic models, FilterDecision dataclass
├── ui/             Flask labeling UI (app, routes, templates, static)
└── http.py         shared HTTP client
```
