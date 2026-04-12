# Soft Similarity Filter: Store All Postings, Recompute on Demand

## Problem

The current pipeline computes similarity scores at ingestion time and uses them as a hard gate: postings below the `similarity_threshold` are discarded and never stored. This means:

1. **Stale scores** — when the user changes their `ideal_role_description`, all existing similarity scores become wrong but there's no way to recompute them (filtered-out postings are gone forever).
2. **Data loss** — postings that would be relevant under new criteria are permanently lost unless re-crawled.
3. **Redundant embedding computation** — `embed_posting()` is called up to 3 times per posting in `_process_posting()` (once inside `filter_posting`, once for the blocklist branch's similarity calc, once for serialization).

## Approach

**Store all postings that pass hard filters (blocklist + location), compute and store their similarity score at ingestion, but never use similarity as a gate for storage.** Provide a CLI command to recompute all similarity scores against an updated ideal role embedding. The similarity threshold continues to control what appears in the digest/UI.

### Approaches Considered

1. **Store everything, recompute on demand** (chosen) — Minimal change, embeddings already stored, recompute is just dot-product arithmetic.
2. **Lazy similarity at query time** — Drop `similarity_score` column, compute on-the-fly. Cleanest conceptually but couples query latency to DB size and makes `WHERE` clauses impossible without views.
3. **Detached embedding storage with hash-based caching** — Track staleness via description hash. Over-engineered for the scale.

## Design

### 1. Ingestion Pipeline Changes

**`quarry/agent/scheduler.py` — `_process_posting()`**

Current flow:
```
raw → extract → dedup → blocklist (discard) → similarity filter (discard low) → store
```

New flow:
```
raw → extract → dedup → blocklist (discard) → embed + score similarity → store (always)
```

Specific changes:
- Remove the `low_similarity` early return path. After blocklist check passes, compute embedding and similarity once, attach both to the `JobPosting` model, and return status `"new"`.
- `embed_posting()` is called exactly once per non-blocklisted, non-duplicate posting. The computed embedding is serialized and set on the posting model directly — no more redundant calls.
- Status strings become: `"new"`, `"duplicate"`, `"duplicate_url"`, `"blocklist"`. The `"low_similarity"` status is removed entirely.
- Blocked postings are still discarded (not stored), just as before.

**`quarry/pipeline/filter.py` — `filter_posting()`**

Refactor to separate concerns:
- `apply_keyword_blocklist()` stays as-is — it's a hard filter.
- The `filter_posting()` function currently embeds, scores, checks blocklist, then checks threshold. Refactor it to just compute and return the similarity score (and optionally the embedding). The threshold gate moves out of this function entirely.
- Simplify `filter_posting()` to return a `(similarity_score: float, embedding: np.ndarray)` tuple instead of `FilterResult`. The caller (`_process_posting`) decides what to do with the score. `FilterResult` is removed entirely.

**`quarry/models.py` — `FilterResult`**

- Remove `FilterResult` entirely. It's no longer needed since similarity no longer gates storage and `filter_posting()` returns `(similarity_score, embedding)` instead.

### 2. Similarity Recomputation CLI

Add a CLI command to `quarry/store/` (or `quarry/agent/tools.py` alongside existing CLI commands):

```
python -m quarry.store recompute-similarity
```

Behavior:
1. Load the current ideal role embedding from the `settings` table. If it doesn't exist, compute it from `settings.ideal_role_description` and store it (same as `_ensure_ideal_embedding()`).
2. Query all postings that have a non-null `embedding` column.
3. For each posting, deserialize the embedding, compute `cosine_similarity(posting_embedding, ideal_embedding)`, and update `similarity_score`.
4. Print a summary: total postings updated, any postings skipped (null embedding).

This is cheap: cosine similarity is a dot product on 384-dim vectors — microseconds per posting. No model inference needed since embeddings are already stored.

The `update_posting_similarity()` method already exists on `Database` and can be used directly. A bulk variant (`update_posting_similarities(posting_id_scores: list[tuple[int, float]])`) would be more efficient for large datasets — batch UPDATE in a single transaction rather than one transaction per posting.

### 3. Digest and UI Query Changes

**`quarry/store/db.py` — `get_recent_postings()`**

Current query:
```sql
SELECT * FROM job_postings
WHERE status = ?
ORDER BY similarity_score DESC
LIMIT ?
```

New query adds a similarity threshold filter:
```sql
SELECT * FROM job_postings
WHERE status = ? AND similarity_score >= ?
ORDER BY similarity_score DESC
LIMIT ?
```

The threshold value comes from `settings.similarity_threshold` (config). The method gains a `threshold` parameter defaulting to `None` (which reads from config).

**`quarry/digest/digest.py`**

The digest already receives postings from `get_recent_postings()` — once the DB query filters by threshold, no additional changes needed in the digest logic itself.

**UI (`quarry/ui/app.py`)**

Any endpoints that query postings should also apply the threshold filter, consistent with `get_recent_postings()`. Currently the UI may need adjustments if it shows all postings regardless of score.

### 4. Schema and Model Changes

**`quarry/store/schema.py`**

No schema changes needed. The `job_postings` table already has `similarity_score REAL` and `embedding BLOB` columns. The only change is that `similarity_score` can now be any float (including values below the threshold) instead of only values above it.

**`quarry/models.py`**

- `FilterResult.skip_reason`: change type from `Literal["duplicate", "blocklist", "low_similarity"]` to `Literal["duplicate", "duplicate_url", "blocklist"]`.
- `FilterResult.passed`: still useful for blocklist results, but reconsider whether this model is still the right abstraction. With similarity no longer a filter, `FilterResult` mainly communicates blocklist status.

### 5. Crawl Log Changes

**`CRAWL_LOG_COLUMNS` and `_log_posting()`**

The crawl log CSV currently logs a `status` field with values `"new"`, `"duplicate"`, `"duplicate_url"`, `"blocklist"`, `"low_similarity"`. The `"low_similarity"` status is removed. Postings that would have been `"low_similarity"` are now logged as `"new"` (since they're stored).

Consider adding a note in the log or a separate column for whether the similarity score is above/below threshold, but this is optional — the `similarity_score` column in the log already conveys this.

### 6. Summary Counts

**`run_once()` summary dict**

Currently tracks:
- `total_found` — all postings discovered
- `total_new` — stored in DB
- `total_duplicates` — skipped as dupes
- `total_filtered` — everything else (blocklist + low_similarity)

After the change, `total_filtered` only means "blocklist". Add a `total_below_threshold` count for postings stored but below the similarity threshold, to give visibility into how many stored postings wouldn't appear in the digest.

### 7. Future: Automatic Recomputation

The CLI approach is sufficient for now. When automatic recomputation is desired, add:

- A `ideal_role_description_hash` setting in the `settings` table, computed as a stable hash (e.g., SHA-256) of the `ideal_role_description` text.
- On each `run_once()`, compare the current description hash with the stored hash. If they differ, trigger the same bulk recompute that the CLI command performs, then update the stored hash.
- This adds minimal overhead: one string comparison per crawl cycle, with recompute only when the description actually changes.

Not in scope for this iteration, but the design supports it cleanly.

## Affected Files

| File | Change |
|------|--------|
| `quarry/agent/scheduler.py` | Rewrite `_process_posting()` to remove low_similarity gate; fix triple-embedding bug; update status strings and summary counts |
| `quarry/pipeline/filter.py` | Simplify `filter_posting()` — remove threshold check; return similarity + embedding instead of FilterResult with pass/fail |
| `quarry/models.py` | Remove `"low_similarity"` from `FilterResult.skip_reason`; simplify or remove `passed` field |
| `quarry/store/db.py` | Add `threshold` parameter to `get_recent_postings()`; add bulk similarity update method |
| `quarry/store/tools.py` or new CLI | Add `recompute-similarity` command |
| `quarry/digest/digest.py` | Pass threshold through to `get_recent_postings()` |
| `quarry/ui/app.py` | Apply threshold filter in posting queries |
| `tests/` | Update existing tests for new pipeline behavior; add tests for `recompute-similarity` |

## Out of Scope

- Changing the embedding model or embedding format
- Location-based hard filtering (separate feature)
- LLM enrichment pipeline changes
- Automatic recomputation on config change (future work)