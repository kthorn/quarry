# Design: Interactive Title/Body Filters on Postings Page

## Goal

Replace the single combined search box on `/postings` with separate **Title** and **Description** text filters that update the posting list instantly as the user types. The purpose is exploratory: understand what is actually in the job corpus before deciding which pipeline filters or ranking rules to add.

## Motivation

The current search box runs an OR across `title` and `description`, which makes it hard to tell whether a posting matched because of the role title or because a keyword appears somewhere in the body. Separate filters let the user discover:

- Which title keywords surface relevant roles.
- Which body keywords correlate with good/bad postings.
- Whether the title or the description is the better signal for a given target role.

That exploration will guide later pipeline changes (e.g., a description-keyword filter or weighted keyword scorer rules).

## UI Changes

### `quarry/ui/templates/postings.html`

- Remove the single `q` search form.
- Add two text inputs side by side inside a `<form>`:
  - **Title contains** (`name="title_q"`)
  - **Description contains** (`name="body_q"`)
- Add a hidden input `name="interest"` so HTMX requests include the currently selected interest tab.
- Add a **Clear filters** link that resets both inputs and interest filter.
- Wrap the results list in `<div id="results">` so HTMX can replace it.
- Interest filter tabs remain above the search fields; their hrefs preserve `title_q` and `body_q`.
- Retrain, Run Scan, label, and pagination controls stay inside or below the results wrapper and preserve `title_q` and `body_q` so they are refreshed together with the list.

### New partial: `quarry/ui/templates/postings_results.html`

- Contains only the results loop and pagination controls.
- Rendered by `/postings` when the request includes `HX-Request: true`.

### HTMX attributes

Each input:

```html
<input
  type="text"
  name="title_q"
  value="{{ title_q }}"
  placeholder="Title contains..."
  hx-get="{{ url_for('ui.postings') }}"
  hx-target="#results"
  hx-trigger="keyup changed delay:300ms"
  hx-include="[name='title_q'],[name='body_q'],[name='interest']"
/>
```

The `hx-include` ensures the current interest tab is sent with every keystroke.

## Server Changes

### `quarry/ui/routes.py`

`/postings` currently accepts `q`, `interest`, and `page`. It will additionally accept:

- `title_q`
- `body_q`

Behavior:

1. Read all query params.
2. Call `db.get_postings_with_scores(..., title_search=title_q or None, body_search=body_q or None, ...)`.
3. If `request.headers.get("HX-Request") == "true"`, render only `postings_results.html`.
4. Otherwise render `postings.html`, which includes `postings_results.html` via `{% include %}`.

All outgoing links (pagination, label forms, retrain, scan) must preserve `title_q` and `body_q`.

### `quarry/store/db.py`

Extend `get_postings_with_scores()`:

```python
def get_postings_with_scores(
    self,
    user_id: int = 1,
    status: str = "new",
    limit: int = 20,
    offset: int = 0,
    search: str | None = None,          # kept for backward compatibility
    title_search: str | None = None,
    body_search: str | None = None,
    interest: str | None = None,
    similarity_threshold: float = 0.0,
) -> list[dict]:
```

Filtering logic:

- If `title_search` is provided, add `ORMPosting.title.ilike(f"%{escaped}%", escape="\\")`.
- If `body_search` is provided, add `ORMPosting.description.ilike(f"%{escaped}%", escape="\\")`.
- If both are provided, combine them with `and_()`.
- The legacy `search` parameter continues to OR title and description for callers that still use it.

Escape logic remains the same (`\`, `%`, `_`).

### `quarry/ui/templates/base.html`

Add HTMX 1.9.12 from unpkg with SRI:

```html
<script
  src="https://unpkg.com/htmx.org@1.9.12"
  integrity="sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"
  crossorigin="anonymous"
></script>
```

## State Persistence

Filters are **not** persisted to the database or `config.yaml`. They live only in the URL query string for the current browsing session. This keeps the feature lightweight and exploratory.

## Accessibility / Fallback

If JavaScript fails to load, the inputs are still inside a normal form with a Search button, so the page degrades to a traditional submit. (HTMX inputs do not need to be in a form, but wrapping them in one provides graceful degradation.)

## Testing

1. **DB layer**: `tests/test_db.py` or new `tests/test_postings_filters.py`
   - `title_search` alone returns matching rows.
   - `body_search` alone returns matching rows.
   - Combined `title_search` + `body_search` returns only rows matching both.
   - Case-insensitive matching works.
   - SQL wildcard characters `%` and `_` are escaped.

2. **Route layer**: `tests/test_ui.py`
   - Normal `GET /postings?title_q=engineer&body_q=python` returns full HTML with populated inputs and results.
   - `GET /postings?title_q=engineer` with `HX-Request: true` returns only the results partial and no `<nav>` or flash-message wrapper.

3. **Template layer** (optional)
   - Verify `postings_results.html` renders without `base.html` context.

## Out of Scope

- Removing the legacy `search` parameter from `get_postings_with_scores` or other callers.
- Adding a description-keyword filter to the pipeline.
- Persisting filters to `UserSettings` or `config.yaml`.
- Live search without debounce.

## Future Work (to be driven by exploration results)

- Add a `DescriptionKeywordConfig` filter to the pipeline if body keywords prove to be a strong signal.
- Promote frequently-used title/body keyword pairs into saved search queries.
- Use exploration data to refine the keyword heuristic scorer rules.
