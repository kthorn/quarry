# Quarry — Agentic Job Search

## Key Commands

```bash
# Install (run from quarry/ directory)
pip install -r requirements.txt

# Setup
cp config.yaml.example config.yaml
python -m quarry.store init          # Initialize SQLite db
python -m quarry.agent.tools seed    # Seed initial data

# Run
python -m quarry.agent.agent --run-once   # Single search cycle
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
- `tests/` — 25 pytest tests

## Notes

- Requirements are in `quarry/requirements.txt`, not repo root
- Config via `config.yaml` (copy from `config.yaml.example`)
- No pyproject.toml, linter, or formatter configured
- Uses raw sqlite3, not ORM
- LLM via AWS Bedrock or OpenRouter (config.yaml)
- Embeddings: sentence-transformers (default: all-MiniLM-L6-v2)