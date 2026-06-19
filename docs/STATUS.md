# STATUS

Last updated: 2026-06-19 (interactive title/body filters on postings page)

## In Progress

_(none)_

## Recent Updates

- **Interactive title/body filters** (2026-06-19): replaced the single combined `q` search box on `/postings` with separate **Title contains** and **Description contains** text inputs that update the list live via HTMX (`keyup changed delay:300ms`). `get_postings_with_scores()` gained `title_search` / `body_search` params (ANDed; legacy `search` OR kept for backward compat). New `postings_results.html` partial rendered for `HX-Request: true` requests; full page otherwise. HTMX 1.9.12 (SRI-pinned) added to `base.html`. All label/retrain/scan/pagination links preserve both filters. Design spec: `docs/superpowers/specs/2026-06-16-interactive-title-body-filters-design.md`. 555 tests passing.

- **Classifier error message improvement**: `quarry/rank/train.py` now reports the exact positive/negative label distribution when training fails due to class imbalance (e.g., "Found 1 interested and 23 not-interested labels..." instead of the generic "at least 5" message).
- **New tests**: `tests/test_rank_train.py` covers single-class, imbalanced, and balanced training scenarios.
- **Test count**: 543 passed, 17 skipped.

## Phase 1 — MVP Progress

| Milestone                              | Status                 | Completed Plan |
| -------------------------------------- | ---------------------- | -------------- |
| M1: Project scaffolding & database     | **DONE**               | 2026-04-05     |
| M2: Crawlers (JobSpy + ATS endpoints)  | **DONE**               | 2026-04-06     |
| M3: Extraction pipeline                | **DONE**               | 2026-04-07     |
| M4: Embedding & similarity filter      | **DONE**               | 2026-04-09     |
| M5: Ranking pipeline & agent tool loop | **DONE**               | 2026-05-05     |
| M6: Scheduler (run-once)               | **DONE** (minimal)     | 2026-04-10     |
| M7: Daily digest                       | **DONE** (file output) | 2026-04-10     |
| M8: Labeling UI                        | **DONE**               | 2026-04-14     |

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
- **UI enhancements** (2026-05-08): score breakdown display (composite/classifier/similarity/fit), keyword search on postings page, retrain classifier button with flash feedback
- **UI enhancements** (2026-05-09): interest signal badges (green/red) on postings, search query persistence across label actions and pagination, "Run Scan" button in toolbar to trigger full crawl cycle from UI, `POST /scan` route, CSS for badge-positive/badge-negative/btn-scan
- **Bug fix (2026-05-08)**: `get_postings_with_scores()` now always LEFT JOINs `user_ranking_scores` (fixes empty results when no active pipeline config)
- **Shared training module**: `quarry/rank/train.py` — `train_classifier()` extracted from CLI for reuse by web UI
- **Crawl log CSV**: ATS crawler 404 handling, noisy log suppression
- **RUNBOOK.md**: pre-execution checklist and operational guide
- **Bug fix (2026-05-03)**: `session_scope()` now invalidates poisoned connections after rollback, preventing `SingletonThreadPool` from handing the same broken connection to the next session (root cause of cascading "readonly database" crashes). `insert_crawl_run` in `run_once()` wrapped in try/except as defense-in-depth.
- **Company page overhaul**: card-based UI with LLM-generated descriptions (Wikipedia → website → LLM), inline editing, em-dash cleanup; LLM client module (`quarry/llm.py`); description generation pipeline (`quarry/resolve/description.py`); trigger integrations on seed/scheduler/add-company; backfill-descriptions CLI; plan refined via pi-refine (8 fixes across 2 review iterations)
- **Settings UI**: (`feature/settings-ui` branch) unified settings page with sidebar layout (7 sections), `UserSettingsService` with config.yaml fallback, search query management (add/retire), all filter configs editable from web UI, JobSpy settings, scheduler integration via service; design spec refined via pi-refine (3 iterations, 2 models); 557 tests passing
- **Company filter simplification** (2026-05-17): removed redundant Company Filter section from Settings UI; company allow/deny is now derived from the watchlist (Active = allow, manually deactivated = deny, search-discovered = allow); `CompanyFilterConfig` still used internally by the pipeline but populated from watchlist state instead of user-editable text fields
- **Schema unification** (2026-05-17): `user_labels` and `user_posting_status` merged into single `user_posting_state` table with nullable boolean `interest` (TRUE=interested, FALSE=not, NULL=unevaluated) and boolean `applied`. Status tabs removed from UI, replaced with interest filter + applied toggle. Classifier training now uses boolean labels instead of string signals. `label_source`, `skip`, `seen`, `rejected`, `archived` concepts all dropped. 540 tests passing, lint/type-check clean. Design spec: `docs/superpowers/specs/2026-05-17-unify-posting-state-design.md`; implementation plan: `docs/plans/completed/2026-05-17-unify-posting-state.md`
- **Hermetic test fixes** (2026-05-17): `test_settings_ui.py`, `test_scheduler.py`, and `test_m4_integration.py` now mock `quarry.pipeline.embedder._get_model` via module-level `autouse` fixtures, preventing real `SentenceTransformer` model loads. Settings UI role-description test dropped from 11s → 0.8s. `test_pipeline_embedder.py` (which intentionally tests the real embedder) skips gracefully when the model is unavailable. Structural fix tracked in [#4](https://github.com/kthorn/quarry/issues/4) (decouple settings writes from embedding computation + injectable `EmbeddingProvider`)
- **Flaky test fix** (2026-06-15): `test_store_cli.py::test_add_company_with_domain` no longer fails with `RuntimeError: Event loop is closed`. `resolve_company_sync()` now closes its HTTP client on the same event loop it creates, and `add_company` uses `resolve_company_sync()` instead of chaining separate `asyncio.run(resolve_company(...))` + `asyncio.run(close_client())` calls.

## Completed Plans & Specs

All completed plans and design specs live in `docs/plans/completed/`:

- `2026-04-05-m1-project-scaffolding.md` — M1: Project scaffolding & database
- `2026-04-06-m2-crawlers-implementation.md` — M2: Crawlers (JobSpy + ATS)
- `2026-04-07-extraction-pipeline.md` — M3: Extraction pipeline
- `2026-04-09-m4-embedding-similarity.md` — M4: Embedding & similarity filter
- `2026-04-10-scheduler-and-digest-minimal.md` — M6/M7: Scheduler + digest (minimal)
- `2026-04-10-seed-data.md` — Seed data (29 companies)
- `2026-04-11-company-cli-design.md` — Company CLI design (add-company)
- `2026-04-11-company-resolver.md` — Company resolver pipeline
- `2026-04-12-haversine-location-matching-design.md` — Haversine location matching
- `2026-04-12-location-normalization.md` — Location normalization
- `2026-04-12-search-cli-design.md` — Search CLI design
- `2026-04-12-unified-filter-pipeline.md` — Unified filter pipeline
- `2026-04-14-company-discovery-design.md` — Company discovery design
- `2026-04-14-m8-labeling-ui.md` — M8: Labeling UI
- `2026-05-05-m5-ranking-pipeline-design.md` — M5: Ranking pipeline design
- `2026-05-08-ui-scores-retrain-search-design.md` — UI: Scores, retrain, search
- `2026-05-09-oracle-escalation-design.md` — Oracle escalation design
- `2026-05-09-ui-improvements-design.md` — UI: Interest badges, run scan
- `2026-05-10-company-page-overhaul-design.md` — Company page overhaul design

**Multi-user schema** (all 4 phases complete) — design spec at `docs/multi-user-schema.md`

**Search-discovered companies**: JobSpy-discovered companies created in shared `companies` table with domain/ATS hints from `company_url_direct`/`job_url_direct` URL patterns; linked via inactive `user_watchlist` entries (`active=False, added_reason='search'`); auto-resolved in background with `asyncio.Semaphore`; surfaced in UI "Discovered" section with Activate button

- **NaN bug fix**: JobSpy DataFrame values sanitized via `_safe_str()` before creating companies/postings

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
- `pyright quarry/` — clean
- `python -m pytest tests/ -q` — **555 passed, 17 skipped** (0 failures)
- **Note:** All four phases complete. All callers use per-user ORM methods with `user_id=1`. `get_recent_postings`/`get_postings_paginated`/`db.execute()` removed. Backward-compat aliases removed from `models.py`.
- **Ranking pipeline:** `python -m quarry.rank list-scorers` — shows 5 registered scorers
- **Ranking CLI:** `python -m quarry.rank config get|set`, `python -m quarry.rank train`, `python -m quarry.rank evaluate`, `python -m quarry.rank recompute`
- **Alembic migration `0848f0dc9297`**: unifies `user_labels` and `user_posting_status` into `user_posting_state` table; `alembic upgrade head` applies cleanly; downgrade re-creates original tables; env.py fixed to place `PRAGMA foreign_keys = ON` inside migration transaction to avoid SQLAlchemy autobegin issue

## Remaining MVP Tasks (from TASKS.md)

### M5: Ranking pipeline & agent tool loop (DONE — ranking pipeline)

- [x] `quarry/rank/` — pluggable scorer framework (similarity, keyword, classifier, LLM, weighted avg)
- [x] `quarry/rank/pipeline.py` — RankingPipeline orchestrator with step reordering
- [x] `quarry/rank/__main__.py` — CLI: list-scorers, config get/set, train, evaluate, recompute
- [x] Pipeline configs stored in `pipeline_configs` table; composite scores in `user_ranking_scores`
- [x] Scheduler integration: ranking phase after crawl, auto-retrain on label threshold
- [x] Digest integration: uses composite scores with similarity fallback
- [x] UI: +/- interest buttons on postings, label collection for classifier training
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
- P2-2: Auto-retrain trigger
- P2-3: Classifier drift reflection
- P3: Breadth expansion (LinkedIn/proxies, generic careers page, Google Jobs)
- UI: config management for ranking pipeline (enable/disable scorers)
- UI: autocomplete/typeahead for keyword search
- UI: FTS index for search at scale (>10k postings)
- UI: search result highlighting
- UI: AJAX for retrain (avoid full page reload)
- P2-3: Classifier drift reflection
- P3: Breadth expansion (LinkedIn/proxies, generic careers page, Google Jobs)

## Multi-User Architecture (Phased)

| Phase                                 | Status   | Design Spec                                   |
| ------------------------------------- | -------- | --------------------------------------------- |
| Phase 1: DDL schema                   | **DONE** | `docs/multi-user-schema.md` (ERD + DDL)       |
| Phase 2: SQLAlchemy 2.0 ORM + Alembic | **DONE** | `docs/multi-user-schema.md` (model reference) |
| Phase 3: CRUD rewrite                 | **DONE** | (incorporated in db.py)                       |
| Phase 4: Caller updates               | **DONE** | (all callers use user_id=1)                   |

Schema documentation: `docs/multi-user-schema.md` (ERD, table docs, design decisions, data migration reference)

## Key Files

```
quarry/
├── agent/          scheduler, tools (seed, recompute-similarity, add-company, normalize-locations), CLI
├── crawlers/       greenhouse, lever, ashby, careers_page, jobspy_client
├── digest/         build + write digest file
├── pipeline/       extract, embedder, filter (FilterStep classes), locations, search
├── rank/           ranking pipeline (scorers, config, registry, CLI)
├── resolve/        company resolver (domain, ATS detection)
├── store/          db.py (ORM CRUD), models.py (ORM Mapped[] classes), session.py (engine + session factory), schema.py (retired)
├── config.py       Settings (Pydantic + YAML), FiltersConfig models
├── models.py       Pydantic API models, FilterDecision dataclass
├── ui/             Flask labeling UI (app, routes, templates, static)
└── http.py         shared HTTP client
alembic/
├── env.py          Alembic environment (targets ORM Base metadata)
└── versions/       4596e16062f9_initial_multi_user_schema.py
                   538837880514_add_ranking_pipeline.py
                   a09b5faf35b6_add_company_description.py
                   0848f0dc9297_unify_posting_state.py
```
