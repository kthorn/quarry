# Quarry — Agentic Job Search

## Key Commands

```bash
# Install (uses CPU-only torch to avoid CUDA dependencies)
pip install -e ".[dev]" -c constraints.txt

# Setup
cp quarry/config.yaml.example quarry/config.yaml
python -m quarry.store init          # Initialize SQLite db
python -m quarry.agent.tools seed    # Seed initial data

# Run
python -m quarry.agent run-once           # Single search cycle
python -m quarry.agent.scheduler          # Continuous scheduler
python -m quarry.ui.app                    # Labeling UI (Flask)
python -m quarry.store --help              # CLI commands

# Test & Lint
python -m pytest                           # Run all tests
ruff check .                               # Lint (auto-fix: --fix)
PYTHONPATH=/home/kurtt/job-search pyright quarry/  # Type check

# Pre-commit hooks (auto-run lint/pyright after git commit)
pre-commit install
```

## Project Structure

- `quarry/` — main Python package (not at repo root)
- `quarry.db` — SQLite database (commit to git; stores all state)
- `docs/STATUS.md` — **always keep updated** as work is done; reflects current milestone progress and next steps
- `tests/` — 198 pytest tests (including seed functionality)
- `constraints.txt` — pins torch to CPU-only build
- `seed_data.yaml` — initial company seed data (29 companies)

## Pre-Execution Checklist

Before running any commands, verify:
1. **Virtual env is active** — you should see `(quarry)` or similar in your prompt, or `which python` points to your venv
2. **Dependencies installed** — `pip install -e ".[dev]" -c constraints.txt` (uses CPU-only torch; do NOT omit `-c constraints.txt` or you'll pull ~2GB of CUDA deps)
3. **Database initialized** — `python -m quarry.store init` (creates `quarry.db` with schema)
4. **Config file exists** — `config.yaml` must be present (copy from `config.yaml.example`)
5. **Seed data loaded** — `python -m quarry.agent.tools seed` (loads companies from `seed_data.yaml`)

## Notes

- Requirements in `pyproject.toml` with `constraints.txt` for CPU-only torch
- Config via `config.yaml` (copy from `config.yaml.example`)
- Linter and formatter configured via pyproject.toml (ruff)
- Uses raw sqlite3, not ORM
- LLM via AWS Bedrock or OpenRouter (config.yaml)
- Embeddings: sentence-transformers (default: all-MiniLM-L6-v2)

## Important: Keep STATUS.md Updated

After completing any milestone, feature, or significant change, **update `docs/STATUS.md`** to reflect the current state. This includes:
- Marking completed milestones as DONE
- Updating test counts
- Adding new completed plans or additional work
- Updating next steps
- Updating verification commands if they change