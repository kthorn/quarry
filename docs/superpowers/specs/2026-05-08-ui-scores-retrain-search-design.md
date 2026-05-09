# Design: UI Enhancements — Score Breakdown, Retrain, Keyword Search

**Date:** 2026-05-08
**Status:** Approved

## Overview

Three changes to the postings UI (`quarry/ui/`):

1. **Score breakdown** — show what kind of score is displayed and its components
2. **Retrain button** — manual classifier retraining from the UI, with result feedback
3. **Keyword search** — simple search box that filters postings by title/description text

## 1. Score Breakdown

### Current behavior

Template shows a single opaque number:
```
score: 0.850
```
Computed as `row.composite_score or row.similarity_score or 0`.

### New behavior

Show a labeled score with components when available:

```
Score: 0.850 (composite) — classifier 0.82 · similarity 0.79 · fit +1
```

**Rules:**
- If `composite_score` exists (ranking pipeline active): label it "(composite)" and show components (`classifier_score`, `similarity_score`, `fit_score`) in smaller text next to it
- If only `similarity_score` exists: show "similarity: 0.850"
- If `role_tier` or `fit_reason` exist: show them as badges or inline text
- Values round to 3 decimal places (matching current format)

### Implementation

Template-only change in `postings.html`. The data is already coming from `get_postings_with_scores()`.

## 2. Retrain Button

### Backend

New route `POST /retrain` in `quarry/ui/routes.py`:

1. Calls a new helper `train_classifier(db)` that wraps the training logic currently in `quarry/rank/__main__.py:cmd_train()`
2. Returns a redirect to `GET /postings` with a flash message containing:
   - Number of training samples
   - Cross-validation accuracy (as percentage, e.g., "83%")
3. If training fails (insufficient labels, no embeddings), flash the error reason

The training logic lives in a shared function so both CLI and web can call it. Extract the core training from `cmd_train()` into `quarry/rank/scorers/classifier.py` (or a separate `train.py`) as a reusable function.

**Flash message format:**
- Success: "Classifier trained on 47 labels (83% cross-validation accuracy)."
- Insufficient: "Not enough labels: 3 labeled postings (need at least 5 with embeddings)."
- Error: "Training failed: no labeled postings with embeddings found."

### UI

- Retrain button in the postings page header (next to the status tabs or in a toolbar)
- Always visible, but disabled with a tooltip reason if labels are insufficient
- After retrain, a flash banner appears at top of page with the result
- Show label count nearby: "47 labels since last train"

### Data for label count

`db.get_user_setting(1, "labels_since_last_train")` returns the count as a string. Parse to int, default 0.

## 3. Keyword Search

### Backend

Add optional `search: str | None = None` parameter to `Database.get_postings_with_scores()`.

When `search` is non-empty, add a WHERE clause:
```sql
AND (job_postings.title LIKE '%' || :query || '%' 
     OR job_postings.description LIKE '%' || :query || '%')
```

This filters server-side, preserving pagination and status filters. Uses SQLite `LIKE` for case-insensitive matching (ASCII only — sufficient for English job postings).

### UI

- Search input above the postings list, between status tabs and the first card
- Submits via GET to `/postings?status=new&q=keyword`
- Input retains its value on reload
- "Clear" link resets to the same status view without search
- If search yields no results, show a message: "No postings match 'keyword'."

### Route

`GET /postings` picks up `q` from `request.args.get("q", "")`, passes `search=q if q else None` to `get_postings_with_scores()`.

## Files Changed

| File | Changes |
|------|---------|
| `quarry/store/db.py` | Add `search` parameter to `get_postings_with_scores()` |
| `quarry/rank/__main__.py` | Extract training logic into shared function |
| `quarry/rank/scorers/classifier.py` | Add reusable `train_classifier()` function (or new `quarry/rank/train.py`) |
| `quarry/ui/routes.py` | New `POST /retrain` route; pass `search` param to `get_postings_with_scores()` in postings route |
| `quarry/ui/templates/postings.html` | Score breakdown display; search box; retrain button; flash messages |

## Tests

- `test_retrain_route` — POST /retrain succeeds with sufficient labels, returns flash message
- `test_retrain_route_insufficient` — POST /retrain with too few labels returns error flash
- `test_search_param` — `get_postings_with_scores(search="engineer")` filters correctly
- `test_search_param_no_results` — search returns empty list gracefully
- `test_search_preserves_status_filter` — search + status filter combine correctly
- Template tests (via existing Flask test client) for score display, search box, retrain button

## Non-Goals

- No JavaScript framework or AJAX — all interactions are form POST + redirect
- No operator syntax (AND/OR/quotes) in search — plain substring matching only
- No highlight of matched terms in search results
- No autocomplete or typeahead
- No config management UI for ranking pipeline (enable/disable scorers) — remains CLI-only
