# UI Improvements: Interest Indicators, Search Persistence, and Job Scan Button

## Objectives

Three targeted UI improvements to make the Quarry labeling UI more usable as the primary interface:

1. Show whether a posting has been marked "Interested" / "Not Interested" at a glance
2. Preserve the search query across page actions (pagination, labeling, retraining)
3. Add a button to trigger a full job scan cycle from the UI

## 1. Interest Indicator

### Data

Interest signals (`positive` / `negative`) are stored in the `user_labels` table alongside status-derived signals (`applied`, `skip`). A user may click both "Interested" and "Not Interested" over time, so the relevant value is the *latest* `positive` or `negative` label for each posting.

### Query change

`Database.get_postings_with_scores()` in `quarry/store/db.py` currently returns a dict per posting with columns from `job_postings`, `companies`, `user_posting_status`, `user_similarity_scores`, `user_classifier_scores`, `user_enriched_postings`, and `user_ranking_scores`. It does **not** include label data.

Add a lateral-left-join scalar subquery to the base SELECT:

```sql
(SELECT signal FROM user_labels
 WHERE user_id = :user_id
   AND posting_id = job_postings.id
   AND signal IN ('positive', 'negative')
 ORDER BY labeled_at DESC
 LIMIT 1) AS interest_signal
```

This returns `"positive"`, `"negative"`, or `None` per row.

### Template change (`postings.html`)

Add a compact badge next to the card title (or in the `card-meta` line) that shows:
- `✅ Interested` in green when `row.interest_signal == "positive"`
- `❌ Not Interested` in red when `row.interest_signal == "negative"`
- Nothing extra when `None` (no interest signal yet)

Styled distinctly from the blue/grey status badges so the interest state is immediately scannable.

### CSS

Add `.badge-positive` (green background, white text) and `.badge-negative` (red background, white text) classes.

## 2. Search Query Persistence

### Root cause

The `POST /label/<id>` route currently reads `return_status` from the form to redirect back to the correct tab, but does **not** read or forward the search query `q`. The redirect loses the search context and drops the user back to the unfiltered list.

### Fix: forms

Each of the five action forms in the posting card needs an additional hidden input:

```html
<input type="hidden" name="q" value="{{ q }}" />
```

The forms to update:
- "Interested" form (signal=positive)
- "Not Interested" form (signal=negative)
- "Applied" form (status=applied)
- "Archive" form (status=archived)

### Fix: label route

In `POST /label/<id>`, read `request.form.get("q", "")` and pass it as the `q` parameter in the redirect to `ui.postings`.

### Fix: retrain route

The retrain form already forwards `q` via a hidden input, and the `/retrain` route already passes it through in the redirect. No change needed here.

### Fix: pagination links

Pagination links in the template already include `q=q`. Verified — no change needed.

## 3. Job Scan Button

### Route

`POST /scan` — calls `run_once()` from `quarry/agent/scheduler.py`, then redirects to the postings page with a flash message summarizing results.

```python
@bp.route("/scan", methods=["POST"])
def scan():
    from quarry.agent.scheduler import run_once

    db = get_db()
    return_status = request.form.get("return_status", "new")
    return_q = request.form.get("q", "")

    try:
        summary = run_once(db, user_id=USER_ID)
        flash(
            f"Scan complete: {summary['total_new']} new, "
            f"{summary['total_duplicates']} duplicates, "
            f"{summary['total_filtered']} filtered, "
            f"{summary['companies_crawled']} companies, "
            f"{summary['companies_errored']} errors."
        )
    except Exception as e:
        flash(f"Scan failed: {e}")

    return redirect(url_for("ui.postings", status=return_status, q=return_q))
```

### Template

Add a "Run Scan" button to the toolbar on the postings page, next to the Retrain Classifier button. The button is a simple form POST (consistent pattern).

```html
<form method="POST" action="{{ url_for('ui.scan') }}" class="inline">
  <input type="hidden" name="return_status" value="{{ status }}" />
  <input type="hidden" name="q" value="{{ q }}" />
  <button type="submit" class="small btn-scan">Run Scan</button>
</form>
```

### CSS

Emphasis styling for the scan button: `btn-scan` class.

## Files Changed

| File | Change |
|------|--------|
| `quarry/store/db.py` | Add `interest_signal` subquery to `get_postings_with_scores()` |
| `quarry/ui/routes.py` | Add `POST /scan` route; read + forward `q` in `POST /label/<id>` |
| `quarry/ui/templates/postings.html` | Add interest badges, search-query hidden inputs, scan button |
| `quarry/ui/static/style.css` | Add `.badge-positive`, `.badge-negative`, `.btn-scan` styles |

## Testing

- Existing test suite: verify no regressions (`python -m pytest tests/ -q`)
- Manual: label a posting, verify indicator appears on page reload
- Manual: search, click pagination, verify `q` persists
- Manual: search, click Interested/Applied/Archive, verify redirect preserves search
- Manual: click Run Scan, verify flash message showing summary
