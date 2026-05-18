# Unify User-Posting State

**Date:** 2026-05-17  
**Status:** Design approved, implementation pending

## Problem

`user_labels` and `user_posting_status` are two overlapping tables that duplicate concepts:

| Concept  | `user_labels.signal` | `user_posting_status.status` |
| -------- | -------------------- | ---------------------------- |
| Applied  | `applied`            | `applied`                    |
| Rejected | `negative` (derived) | `rejected`                   |
| Seen     | `negative` (derived) | `seen`                       |
| Archived | `skip` (derived)     | `archived`                   |

`user_labels` has `UNIQUE(user_id, posting_id, signal)`, so `positive` and `negative` can coexist for the same posting. The application resolves ambiguity via a "latest `labeled_at` wins" subquery, which is fragile and opaque.

## Design

Replace both tables with a single `user_posting_state` table. One row per `(user_id, posting_id)`.

### Schema

```sql
CREATE TABLE user_posting_state (
    user_id      INTEGER NOT NULL,
    posting_id   INTEGER NOT NULL,
    interest     BOOLEAN,                       -- TRUE=interested, FALSE=not, NULL=unevaluated
    applied      BOOLEAN NOT NULL DEFAULT 0,
    notes        TEXT,
    labeled_at   DATETIME,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, posting_id),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(posting_id) REFERENCES job_postings(id) ON DELETE CASCADE
);
CREATE INDEX idx_state_user ON user_posting_state(user_id);
CREATE INDEX idx_state_posting ON user_posting_state(posting_id);
CREATE INDEX idx_state_interest ON user_posting_state(user_id, interest);
```

- `interest` is a nullable boolean — three states in one column, no CHECK constraint needed
- `applied` is a non-nullable boolean
- `labeled_at` records when interest was last changed (relevant for `labels_since_last_train`)
- `label_source` is dropped — never used

### Migration (Alembic)

1. `op.create_table("user_posting_state", ...)` with schema above
2. No data migration — existing interest labels are untrusted (seen auto-marked negative)
3. `op.drop_table("user_labels")`
4. `op.drop_table("user_posting_status")`

### Model (`quarry/store/models.py`)

- Remove `UserLabel` class entirely
- Remove `UserPostingStatus` class entirely
- Add `UserPostingState` class with ORM mapping for the new table
- Remove `labels` and `statuses` relationships from `User`

### Database Layer (`quarry/store/db.py`)

**Removed methods:**

- `insert_label`
- `get_labels_for_posting`
- `update_posting_status`
- `_interest_signal_subquery`

**New / changed methods:**

| Method                                                   | Behavior                                                                                                                                                                             |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `set_interest(user_id, posting_id, value: bool \| None)` | Upsert `interest`, set `labeled_at = now()`, increment `labels_since_last_train`, set `retrain_pending` when threshold reached                                                       |
| `set_applied(user_id, posting_id, value: bool)`          | Upsert `applied`, set `updated_at = now()`                                                                                                                                           |
| `get_postings_with_scores(...)`                          | Replace `_interest_signal_subquery` with direct column read. Interest filter: `interest` → `interest = TRUE`, `not_interested` → `interest = FALSE`, `untagged` → `interest IS NULL` |
| `get_labeled_embeddings(user_id)`                        | Change from `signal IN ('positive','negative')` to `interest IS NOT NULL`. Return `(interest_bool, embedding, posting_id)` instead of `(signal_str, ...)`.                           |
| `count_postings_by_watchlist(...)`                       | Remove status-based counting. Replace with interest + applied counts.                                                                                                                |

### Interest Signal Concepts

| Old                   | New                |
| --------------------- | ------------------ |
| signal = `'positive'` | `interest = TRUE`  |
| signal = `'negative'` | `interest = FALSE` |
| No signal             | `interest IS NULL` |
| signal = `'applied'`  | `applied = TRUE`   |
| signal = `'skip'`     | Removed            |

### Classifier Training (`quarry/rank/train.py`, `quarry/rank/scorers/classifier.py`)

- Labels change from `"positive"`/`"negative"` strings to `True`/`False` booleans
- `get_labeled_embeddings` returns `(bool, embedding_bytes, posting_id)` tuples
- `y_list` construction: `1 if label else 0`

### UI Changes (`quarry/ui/routes.py`, `quarry/ui/templates/postings.html`)

**Route `/label/<posting_id>` (POST):**

- Accept `interest` form field: `"positive"`, `"negative"`, or absent
- Accept `applied` form field: `"true"` or absent
- Call `set_interest()` and/or `set_applied()` accordingly
- Remove `STATUS_TO_SIGNAL` mapping
- Remove `VALID_STATUSES` and status tabs

**Template changes:**

- Remove status tabs (New, Seen, Applied, Rejected, Archived)
- Interest filter remains: All, Interested, Not Interested, Untagged
- Interest badges remain (map `interest=True` → "Interested", `interest=False` → "Not Interested")
- The Applied button toggles `applied = TRUE`
- Add `applied` badge on cards
- Remove Archive button

**Interest filter values:**

- `"interested"` → `interest = TRUE`
- `"not_interested"` → `interest = FALSE`
- `"untagged"` → `interest IS NULL`

### Pydantic Models (`quarry/models.py`)

- Remove `UserLabel` dataclass
- Add `UserPostingState` dataclass

### Test Impact

Tests that directly interact with `user_labels` or `user_posting_status` need updating. Key areas:

- `tests/test_db.py`: Replace `insert_label`/`update_posting_status` tests with `set_interest`/`set_applied` tests. Verify mutual exclusion (setting TRUE after FALSE replaces it).
- `tests/test_ui.py`: Update label/status route tests. Update template tests (no status tabs, no archive button).
- `tests/test_rank_classifier.py`: Update label format from strings to booleans.

## Verification

```bash
python -m pytest                        # All tests pass
ruff check .                            # Lint clean
PYTHONPATH=. pyright quarry/            # Type check clean
alembic upgrade head                    # Migration applies cleanly (dry run first)
```
