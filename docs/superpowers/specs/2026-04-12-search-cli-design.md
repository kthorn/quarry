# Search CLI — Job Testing & Filtering Tool

## Purpose

A CLI tool for testing and debugging job search relevance. Supports two composable operations:
1. Score all jobs in the DB against a new ideal role description (without modifying stored data)
2. Filter jobs by whole-word keyword matches in title and/or description

These can be used independently or composed (prefilter by keywords, then rank by similarity).

## Command

```
python -m quarry.pipeline.search [OPTIONS]
```

At least one of `--ideal`, `--must-have-title`, or `--must-have-description` is required. If none are provided, show help.

## Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--ideal TEXT` | string | — | Ideal role description; embed and score all matching postings against it |
| `--must-have-title WORDS` | string | — | Comma-separated words; keep postings where ANY word matches in the title |
| `--must-have-description WORDS` | string | — | Comma-separated words; keep postings where ANY word matches in the description |
| `--limit N` | int | 20 | Maximum number of results to display |
| `--min-score FLOAT` | float | 0.0 | Minimum similarity score to include in results |
| `--status STATUS` | string | — | Filter by posting status (default: show all statuses) |

## Behavior

### Processing Pipeline

1. **Load postings** from DB. If `--status` is set, filter to that status only.
2. **Keyword prefilter** (if `--must-have-title` or `--must-have-description` is provided):
   - `--must-have-title`: keep postings where ANY word in the list matches the title (whole-word, case-insensitive)
   - `--must-have-description`: keep postings where ANY word in the list matches the description (whole-word, case-insensitive)
   - When both flags are provided, both conditions must be met (AND between flags, OR within each flag's word list)
3. **Similarity scoring** (if `--ideal` is provided):
   - Embed the ideal description using the existing `embed_text()` function
   - For each remaining posting, compute cosine similarity against the ideal embedding using stored embeddings or by calling `embed_posting()` on the description text
   - Sort by similarity score descending
   - Apply `--min-score` filter
4. **Default sort** (if only `--must-have-*` with no `--ideal`): sort by `first_seen_at` descending (newest first)
5. **Output**: terminal table, capped at `--limit` rows

### Keyword Matching

Whole-word matching using `re.search(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE)`.

- "python" matches "Python Developer" and "python" but not "pythonic"
- Case-insensitive
- OR within a single flag's word list, AND between flags

### Embedding Source

For similarity scoring, use the stored `embedding` BLOB from each posting (already computed during the crawl pipeline). This avoids re-embedding every posting on each search invocation. If a posting lacks an embedding, skip it from similarity results (it wouldn't have been scored anyway).

For the ideal role embedding, compute it fresh each invocation using `embed_text()`.

## Output Format

Terminal table with columns:

| Column | Shown When |
|--------|-----------|
| Rank | Always (1-based) |
| Title | Always |
| Company | Always |
| Similarity | When `--ideal` is provided |
| Matched Title Keywords | When `--must-have-title` is provided |
| Matched Desc Keywords | When `--must-have-description` is provided |

## Examples

```bash
# Rank jobs by similarity to a hypothetical ideal role
python -m quarry.pipeline.search --ideal "senior python backend engineer"

# Filter: title must mention "senior" or "lead"
python -m quarry.pipeline.search --must-have-title "senior,lead"

# Filter: description must mention "python" or "aws"
python -m quarry.pipeline.search --must-have-description "python,aws"

# Compose: prefilter by title keywords, then rank by similarity
python -m quarry.pipeline.search --must-have-title "senior,lead" --ideal "senior python backend engineer"

# Full composition: both keyword filters + similarity + limit
python -m quarry.pipeline.search \
  --must-have-title "senior,lead" \
  --must-have-description "python,aws" \
  --ideal "senior python backend engineer" \
  --limit 10 --min-score 0.5
```

## Implementation Notes

- Add `search` as a subcommand in the existing `quarry/pipeline/__main__.py` Click group (alongside the existing `embed-ideal` command)
- Implementation in a new `quarry/pipeline/search.py` module — keep logic out of the CLI file for testability
- Reuse existing functions: `embed_text()`, `cosine_similarity()`, `deserialize_embedding()` from `quarry/pipeline/embedder.py` and `quarry/pipeline/filter.py`
- Add a new DB method to fetch postings with embeddings (extend store/db.py; reuse `get_recent_postings()` pattern but without the threshold/status assumptions)
- Add `tabulate` as a dependency in `pyproject.toml` for clean table output

## Not In Scope

- Modifying stored data (this is read-only / testing only)
- Persisting search results
- Full-text search / advanced query syntax
- Exporting results to file (can be added later if needed)