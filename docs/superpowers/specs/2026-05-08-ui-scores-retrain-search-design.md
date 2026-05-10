# Design: UI Enhancements — Score Breakdown, Retrain, Keyword Search

**Date:** 2026-05-08
**Status:** Refined (4 iterations, 3 models)

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
- If `role_tier` or `fit_reason` exist: show them as badges or inline text (requires CSS classes in `style.css` for role-tier badges, e.g., `.badge-reach`, `.badge-match`, `.badge-strong-match`)
- Float values round to 3 decimal places; `fit_score` is an integer — display as-is (e.g., `+1`, `−2`). When `fit_score` is `0` or `None`, omit the fit component entirely.

### Implementation

Template-only change in `postings.html`. The data is already coming from `get_postings_with_scores()`.

## 2. Retrain Button

### Backend

New route `POST /retrain` in `quarry/ui/routes.py`:

1. Calls a shared `train_classifier(db, min_labels=5)` function that handles the full training lifecycle:
   - Phase 1: `ClassifierScorer.fit()` — trains logistic regression on labeled embeddings, returns metrics dict with `cv_auc_mean` (ROC AUC)
   - Phase 2: Persists `ClassifierVersion` ORM row, saves model pickle, deactivates prior versions, resets `labels_since_last_train` and `retrain_pending` counters
2. Accepts optional `return_status` (default `"new"`) and `q` query params to preserve the current view after retrain.
3. Returns a redirect to `url_for("ui.postings", status=return_status, q=q)` with a flash message containing:
   - Number of training samples
   - Cross-validation AUC (e.g., "AUC: 0.83") — note: this is ROC AUC, not a percentage accuracy
4. If training fails (insufficient labels, no embeddings), flash the error reason

The training logic lives in a shared function so both CLI and web can call it. Extract the combined Phase 1+2 logic from `cmd_train()` into `quarry/rank/scorers/classifier.py` (or a new `quarry/rank/train.py`) as `train_classifier(db, min_labels=5)`. The function returns a dict with keys `training_samples` (int), `cv_auc_mean` (float), and optionally `error` (str). The `db` parameter provides engine access; the function handles its own session management.

**Implementation notes:**

- `db.get_labels_with_postings()` returns `(UserLabel, embedding_bytes, posting_id)` tuples — not `(UserLabel, JobPosting)` as the docstring incorrectly claims. `train_classifier()` must unpack the 3-tuple pattern that `cmd_train()` already follows.
- The ORM `ClassifierVersion.cv_accuracy` column stores ROC AUC (not accuracy percentage) — this is a pre-existing naming mismatch the plan inherits.
- `ClassifierVersion` has no `user_id` column — the current `cmd_train()` deactivates all prior versions globally. For now (single-user, `USER_ID=1`), this is harmless. The plan does not add multi-user scoping; it follows the existing pattern.
- Model save path must use an absolute path (`Path(__file__).parent.parent / "models"`) rather than the current relative `Path("quarry/models")` in both `cmd_train()` and `_get_models_dir()`.
- The retrain button's disabled threshold should use the same value as `min_labels` default (5). Users can attempt training on small label sets and see the result even if the `ClassifierScorer` default `min_training_labels` is higher (20).
- `train_classifier()` should return `model_path` in its result dict so the CLI can continue printing the save path after refactoring.
- Place `train_classifier()` in a new `quarry/rank/train.py` module (not in `classifier.py`) to keep the scorer pure and avoid coupling it to the ORM/storage layer.

**Dependencies:**

- The `POST /retrain` route must import `flash` from Flask.
- The Flask app factory (`quarry/ui/app.py`) must set `app.secret_key` — `flash()` requires a session secret. Use `app.secret_key = os.urandom(24).hex()` or similar.
- The `base.html` template must render flashed messages (it currently lacks a `get_flashed_messages()` block). Place it inside `<main>` before `{% block content %}` for good UX.

**Flash message format:**

- Success: "Classifier trained on 47 labels (AUC: 0.83)."
- Insufficient: "Not enough labels: 3 labeled postings (need at least 5 with embeddings)."
- Error: "Training failed: no labeled postings with embeddings found."

### UI

- Retrain button in the postings page header (next to the status tabs or in a toolbar)
- Always visible, but disabled with a tooltip reason if labels are insufficient
- After retrain, a flash banner appears at top of page with the result
- Show label count nearby: "47 labels since last train"

### Data for label count

Add a convenience method `db.get_user_setting(user_id: int, key: str) -> str | None`:

```python
def get_user_setting(self, user_id: int, key: str) -> str | None:
    return self.get_user_settings_raw(user_id).get(key)
```

`dict.get(key)` returns `None` for both missing keys and keys with `None` values — both are handled correctly by the calling pattern `int(result or "0")`. Unlike `(dict.get(key) or None)`, this preserves empty-string `""` values (though no current settings store them).

Callers use `int(db.get_user_setting(1, "labels_since_last_train") or "0")`.

The counter is already incremented by `insert_label()` on each positive/negative signal (not on "applied" or "archived" status changes). The UI label should say "N interest labels" to be precise.

## 3. Keyword Search

### Backend

Add optional `search: str | None = None` parameter to `Database.get_postings_with_scores()`.

When `search` is non-empty, add a filter using SQLAlchemy (not raw SQL):

```python
from sqlalchemy import or_
stmt = stmt.where(
    or_(
        ORMPosting.title.ilike(f"%{search}%"),
        ORMPosting.description.ilike(f"%{search}%"),
    )
)
```

This filters server-side, preserving pagination and status filters. SQLAlchemy's `ilike` with SQLite behaves case-insensitively for ASCII A-Z. Note: this is a full-text scan on `description` (TEXT column with no index) — acceptable for single-user internal use, but may need an FTS index if the posting count grows into the tens of thousands.

### UI

- Search input above the postings list, between status tabs and the first card
- Uses a `<form method="GET" action="{{ url_for('ui.postings') }}">` with the search input named `q` and a hidden input for the current `status` filter (so search + status tabs work together)
- Input retains its value on reload (via `value="{{ request.args.get('q', '') }}"`)
- "Clear" link resets to `?status={{ status }}` (removes `q` parameter)
- Status tab links do NOT include `q` — clicking a tab resets the search (standard UX: tabs show unfiltered counts)
- If search yields no results, show: "No postings match 'keyword'."
- If a tab has zero postings (no search active), show the existing message: `No postings with status "X" found.`
- Template must distinguish these two cases: `{% if request.args.get('q') %}...search message...{% else %}...tab-empty message...{% endif %}`

### Route

`GET /postings` picks up `q` from `request.args.get("q", "")`, passes `search=q if q else None` to `get_postings_with_scores()`.

## Files Changed

| File                                | Changes                                                                                                                                                                  |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `quarry/store/db.py`                | Add `search` parameter to `get_postings_with_scores()`; add `get_user_setting()` convenience method                                                                      |
| `quarry/rank/__main__.py`           | Refactor `cmd_train()` to call shared `train_classifier(db, min_labels)`                                                                                                 |
| `quarry/rank/scorers/classifier.py` | Add reusable `train_classifier(db, min_labels)` function handling fit + persist + model save + counter reset; fix model path to absolute (or new `quarry/rank/train.py`) |
| `quarry/ui/routes.py`               | New `POST /retrain` route; import `flash`; pass `search` param to `get_postings_with_scores()` in postings route                                                         |
| `quarry/ui/app.py`                  | Set `app.secret_key` (required for Flask `flash()`)                                                                                                                      |
| `quarry/ui/templates/base.html`     | Add `{% with messages = get_flashed_messages() %}` block inside `<main>` before `{% block content %}`                                                                    |
| `quarry/ui/templates/postings.html` | Score breakdown display; search box (`<form method="GET">` with hidden status input); retrain button                                                                     |
| `quarry/ui/static/style.css`        | CSS classes for role-tier badges (`.badge-reach`, `.badge-match`, `.badge-strong-match`) if used                                                                         |

## Tests

- `test_retrain_route` — POST /retrain succeeds with sufficient labels, returns flash message (requires fixture with labeled postings that have embeddings)
- `test_retrain_route_insufficient` — POST /retrain with too few labels returns error flash
- `test_retrain_redirect_preserves_status` — POST /retrain?return_status=applied preserves the status tab
- `test_search_param` — `get_postings_with_scores(search="engineer")` filters correctly
- `test_search_param_no_results` — search returns empty list gracefully
- `test_search_preserves_status_filter` — search + status filter combine correctly
- `test_search_pagination_preserves_query` — pagination links include `q` parameter when searching
- Template tests (via existing Flask test client) for score display, search box, retrain button

**Test fixture requirements:** Retrain tests need postings with serialized embeddings (`numpy` arrays from `quarry.pipeline.embedder`) and `UserLabel` rows. The existing `app_with_postings` fixture in `test_ui.py` does not include embeddings — create a new `app_with_labeled_embeddings` fixture.

## Non-Goals

- No JavaScript framework or AJAX — all interactions are form POST + redirect
- No operator syntax (AND/OR/quotes) in search — plain substring matching only
- No highlight of matched terms in search results
- No autocomplete or typeahead
- No config management UI for ranking pipeline (enable/disable scorers) — remains CLI-only
- No concurrency protection on retrain (single-user internal tool — retrains are rare and user is the only initiator)

## Edge Cases

- **Empty search query:** `search=""` or `search=None` adds no filter (backward compatible)
- **Search with special characters:** SQLAlchemy's `ilike` does NOT auto-escape `%` or `_` (LIKE wildcards). A search for `100%` would match everything. Explicitly escape before constructing the pattern:

```python
escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
ORMPosting.title.ilike(f"%{escaped}%", escape="\\")
```

- **Retrain with no labels:** Returns error flash; button should be disabled when count is 0
- **Retrain when model save fails:** Disk write errors are caught and flashed; previous model version remains active
- **Model save path:** Use an absolute path derived from the package root (not relative `quarry/models/`) to work regardless of web server CWD
- **Concurrent retrains:** Not guarded — single-user internal tool, retrains are rare and user-initiated
- **Pagination loses search query:** Pagination links (`url_for('ui.postings', ...)`) must include `q=request.args.get('q', '')` to preserve search across pages. Currently pagination only passes `status` and `page`.
- **fit_score NULL vs 0:** The query coalesces `NULL` to `0`, making them indistinguishable. For now, both are treated as "no fit data" and omitted from display. If displaying a genuine `fit_score == 0` becomes important later, the query should expose the raw column.
