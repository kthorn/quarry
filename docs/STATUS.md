# STATUS

Last updated: 2026-04-12

## Phase 1 — MVP Progress

| Milestone | Status | Completed Plan |
|-----------|--------|-----------------|
| M1: Project scaffolding & database | **DONE** | 2026-04-05 |
| M2: Crawlers (JobSpy + ATS endpoints) | **DONE** | 2026-04-06 |
| M3: Extraction pipeline | **DONE** | 2026-04-07 |
| M4: Embedding & similarity filter | **DONE** | 2026-04-09 |
| M5: Agent tool loop & strategy reflection | **NOT STARTED** | — |
| M6: Scheduler (run-once) | **DONE** (minimal) | 2026-04-10 |
| M7: Daily digest | **DONE** (file output) | 2026-04-10 |
| M8: Labeling UI | **NOT STARTED** | — |

## Additional Work (Beyond TASKS.md)

- **Seed data**: 29 AI/robotics companies in `seed_data.yaml` with `python -m quarry.agent.tools seed`
- **Company resolver pipeline** (`quarry/resolve/`): domain resolution, careers URL detection, ATS type detection, `add-company` CLI command
- **Location filter design spec**: added to docs
- **Location normalization**: structured location parsing with `quarry/pipeline/locations.py`, `work_model` replacing `remote` boolean, `locations` + `job_posting_locations` tables, geonamescache-based resolution, location filtering in pipeline
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
7. `2026-04-12-location-normalization.md` (in `docs/superpowers/plans/`)

## Verification

- `python -m quarry.store init` — initializes database
- `python -m quarry.agent.tools seed` — loads seed companies
- `python -m quarry.agent run-once` — single search cycle (mocked crawlers work; live crawlers need API keys)
- `python -m quarry.digest` — writes ranked digest file
- `python -m quarry.agent.tools normalize-locations` — parse and normalize location data for existing postings
- `python -m pytest tests/` — **249 tests passing**

## Next Steps

1. **M8: Web UI for controlling Quarry** — Browser-based interface to run crawls, view postings, label results, manage companies/queries, and trigger digests. Starts local; eventually deployed to EC2
2. **M5: Agent tool loop & strategy reflection** — LLM-based agent that reads strategy state and makes tool calls (add/retire companies, queries)
3. **Deploy to EC2** — Package for production deployment on an EC2 instance (systemd service, Quarry as reverse proxy, TLS)
4. M6/M7 enhancements: APScheduler for automated scheduling, email/Slack digest delivery

## Key Files

```
quarry/
├── agent/          scheduler, tools (seed), CLI
├── crawlers/       greenhouse, lever, ashby, careers_page, jobspy_client
├── digest/         build + write digest file
├── pipeline/       extract, embedder, filter, locations
├── resolve/        company resolver (domain, ATS detection)
├── store/          db.py, schema.sql
├── config.py       Settings (Pydantic + YAML)
├── models.py       Pydantic models
└── http.py         shared HTTP client
```