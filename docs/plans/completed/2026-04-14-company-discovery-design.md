# Company Discovery Agent — Design Spec

Date: 2026-04-14

## Problem

Quarry's company watchlist is currently populated manually — via seed YAML or the `add-company` CLI. There is no mechanism to discover new companies that are similar to existing ones or in a given domain. Users must identify and add companies one at a time.

## Goal

Build a discovery agent that takes example companies and/or domain descriptions, finds additional companies the user would want to track, and adds them to the watchlist. The agent should use LLM reasoning to generate search strategies and evaluate results, with Exa search as its information source.

## Approach

LLM agent loop with Exa search as a tool. The LLM drives its own search-and-evaluate cycle, calling `exa_search` as needed. This avoids building throwaway orchestration and makes future migration to a strategy-reflection agent tool trivial.

## Architecture

```
Input (--similar, --domain) + existing company context from DB
          │
          ▼
   ┌──────────────────────────────┐
   │  LLM Agent Loop              │
   │                              │
   │  System prompt includes:    │
   │  - existing companies in DB │
   │  - discovery goal            │
   │  - available tool: exa_search│
   │                              │
   │  Loop:                       │
   │    LLM calls exa_search      │──→ Exa API
   │    LLM reviews results       │    returns results
   │    LLM decides: search more  │    back to LLM
   │               or finalize    │
   └──────────────┬───────────────┘
                  │ finalized company list
                  ▼
          ┌──────────────────┐
          │ Resolve & Add     │
          │ - Dedup vs DB     │
          │ - Resolve pipeline│
          │ - Insert companies│
          └──────────────────┘
```

## Components

### 1. Exa Client (`quarry/discover/exa_client.py`)

A thin async wrapper around the Exa search API.

- **Authentication**: `EXA_API_KEY` env var or `exa_api_key` in config.yaml
- **Search endpoint**: Exa `search` with `type: "auto"`, supports `category: "company"` filter
- **Result fields**: `name`, `url`, `text` (snippet) — everything the LLM needs for evaluation
- **Rate limiting**: tracked by `max_searches` param; raises when budget exhausted
- **Error handling**: network errors are logged and re-raised; the agent loop catches them and can reformulate

New config fields in `Settings`:

```python
exa_api_key: str = ""  # or from EXA_API_KEY env var
exa_max_searches: int = 10  # max Exa API calls per discover invocation
```

### 2. LLM Agent Loop (`quarry/discover/agent.py`)

An agentic loop that gives the LLM the `exa_search` tool and lets it drive discovery.

**Tool definition**:
```json
{
  "name": "exa_search",
  "parameters": {
    "query": "search query string",
    "category": "company (optional)",
    "max_results": 10
  }
}
```

**System prompt** includes:
- The list of existing companies in the DB (name, domain, added_reason) so the LLM can avoid duplicates
- The discovery goal derived from `--similar` and `--domain` args
- Instructions to search, evaluate, and finalize a list of new companies
- Guidance on when to stop (enough results, no more productive queries)

**Loop guardrails**:
- `max_iterations` (default 5) — hard stop on LLM rounds
- `max_searches` (default 10) — hard stop on Exa API calls across the entire run
- A search budget counter passed into the agent context, decremented on each `exa_search` call

**Agent output** (final structured message):
```json
{
  "companies": [
    {"name": "Sanctuary AI", "domain": "sanctuary.ai", "reason": "Humanoid robotics, Phoenix robot"}
  ]
}
```

**LLM provider**: uses the existing `llm_provider` / `openrouter_api_key` / `aws_region` config. Since no shared LLM client exists yet (M5 is not started), this module will include a thin LLM client wrapper (`quarry/discover/llm.py`) that handles OpenRouter or Bedrock invocation with tool calling support. This wrapper will later be extracted to a shared module when M5 is built.

### 3. Resolve & Add (`quarry/discover/resolve_add.py`)

Post-processing of the agent's company list using existing infrastructure:

1. **Dedup**: Check DB by domain first (if candidate has domain), then by name (case-insensitive). Skip any already tracked.
2. **Resolve**: Run `quarry.resolve.pipeline.resolve_company()` for each new company — domain resolution, careers URL detection, ATS type detection.
3. **Insert**: Companies that resolve successfully get `added_by="discover"`, `added_reason=<original prompt>`. Companies that fail resolution are skipped unless `--allow-unresolved`.

### 4. CLI Interface (`quarry/agent/tools.py` — new `discover` command)

```
python -m quarry.agent discover --similar "Figure AI,Boston Dynamics" --domain "warehouse robotics"
```

**Options**:
- `--similar` — comma-separated company names from DB to find similar companies
- `--domain` — free-text domain description (e.g., "AI safety startups", "warehouse robotics")
- `--max-searches` — max Exa API calls (default from config: 10)
- `--max-iterations` — max LLM rounds (default 5)
- `--min-results` — target number of new companies before stopping (default 5)
- `--preview` — show candidates without adding to DB
- `--allow-unresolved` — add companies even if resolver fails
- At least one of `--similar` or `--domain` is required
- `--similar` names must match companies already in the DB; the CLI validates this before starting the agent loop

**Output**: human-readable summary like:

```
Discovery: "warehouse robotics"
Found 6 new companies, 2 already tracked, 0 unresolved

NEW:
  Sanctuary AI (sanctuary.ai) — Humanoid robotics, Phoenix robot
  Agility Robotics (agilityrobotics.com) — Digit humanoid robot
  ...

ALREADY TRACKED:
  Boston Dynamics
  Figure AI
```

## Module Structure

```
quarry/discover/
├── __init__.py
├── agent.py          # LLM agent loop with exa_search tool
├── exa_client.py     # Exa API client
└── resolve_add.py    # Dedup, resolve, insert pipeline
```

The CLI entrypoint stays in `quarry/agent/tools.py` alongside the existing `seed` command.

## Testing Strategy

- **Exa client**: mock Exa API responses; test rate limiting, error handling, result parsing
- **Agent loop**: mock LLM responses with tool calls; test that the loop correctly executes tool calls, accumulates results, and stops at guardrails
- **Resolve & add**: integration test with in-memory SQLite; test dedup by domain and name, resolve success/failure, `--allow-unresolved` flag
- **CLI**: test discover command with mocked agent and DB, verify preview mode, required args

## Future Work

- **Agent tool**: expose `discover` as a tool the strategy reflection agent can call during scheduled runs
- **UI integration**: add a "Discover companies" form to the labeling UI
- **Relevance scoring**: after discovery, crawl the new companies' job listings and score relevance before surfacing in digest
- **Discovery history**: track which discovery runs produced which companies, so users can review and retire discovery-sourced companies