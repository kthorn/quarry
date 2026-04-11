# Seed Data + Seed Command Design

## Problem
Without companies in the DB, no crawlers or agents can run. We need a way to populate the database with an initial set of target companies.

## Solution

### 1. `seed_data.yaml` — Company data file

A YAML file at the project root containing a list of company records. Each record maps to the `Company` model fields:

```yaml
- name: OpenAI
  domain: openai.com
  ats_type: greenhouse
  ats_slug: openai
  crawl_priority: 7
  added_reason: Leading AI lab
```

Fields:
| Field | Required | Notes |
|-------|----------|-------|
| `name` | yes | Company name (used for dedup) |
| `domain` | no | e.g. `openai.com` |
| `careers_url` | no | Direct careers page URL |
| `ats_type` | no | One of: greenhouse, lever, ashby, generic, unknown |
| `ats_slug` | no | ATS board slug (e.g. `openai` for Greenhouse) |
| `crawl_priority` | no | 1-10, default 5 |
| `notes` | no | Any context |
| `added_reason` | no | Why this company was added |

~25 AI/robotics/cutting-edge-tech companies with real Greenhouse/Lever/Ashby slugs where available.

### 2. `quarry/agent/tools.py::seed()` — Seed function

Thin wrapper that:
1. Reads `seed_data.yaml` (path from `settings.seed_file`)
2. Creates `Company` models from each YAML entry
3. Calls `db.insert_company()` for each, skipping duplicates (by name)
4. Prints summary: X inserted, Y skipped

Invoked via: `python -m quarry.agent.tools seed`

### 3. `quarry/agent/__init__.py` and CLI entry point

Minimal package scaffolding so `python -m quarry.agent.tools seed` works. The `tools.py` module has a `seed()` function and a `__main__`-style CLI entry point using click or argparse.

### Error Handling

- DB not initialized → print error and exit
- YAML file missing → print error and exit
- Duplicate companies (by name) → silently skipped, counted in summary

## Out of Scope

- Updating existing companies (seed is insert-only)
- Seeding job postings or search queries
- Interactive company addition (that's for the agent)