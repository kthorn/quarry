# UI Enhancements — Score Breakdown, Retrain, Keyword Search

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add score breakdown display, classifier retrain button, and keyword search to the postings UI.

**Architecture:** Three features targeting `quarry/ui/` (routes, templates, static) and `quarry/store/db.py` (query + convenience method). The retrain feature extracts training logic from `quarry/rank/__main__.py` into a shared `quarry/rank/train.py` module. All features follow existing Flask POST-redirect-GET patterns.

**Tech Stack:** Flask (routes, templates, flash messages), SQLAlchemy (ORM queries), Pydantic (existing models), pytest (testing)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `quarry/rank/train.py` | Shared `train_classifier()` function (extracted from `__main__.py`) |
| Modify | `quarry/store/db.py` | Add `search` param to `get_postings_with_scores()`, add `get_user_setting()` |
| Modify | `quarry/rank/__main__.py` | Refactor `cmd_train()` to call `train_classifier()` |
| Modify | `quarry/ui/routes.py` | Add `POST /retrain` route, pass `q` param to postings, import `flash` |
| Modify | `quarry/ui/app.py` | Set `app.secret_key` |
| Modify | `quarry/ui/templates/base.html` | Add flash message rendering |
| Modify | `quarry/ui/templates/postings.html` | Score breakdown, search box, retrain button |
| Modify | `quarry/ui/static/style.css` | Role-tier badge styles, retrain button, search box, flash messages |
| Modify | `tests/test_db.py` | Tests for `search` param, `get_user_setting()` |
| Modify | `tests/test_ui.py` | Tests for retrain route, search route, updated postings view |

---

### Task 1: Add `search` parameter to `get_postings_with_scores()`

**Files:**
- Modify: `quarry/store/db.py:795-918` (the `get_postings_with_scores` method)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for search parameter**

Add to `tests/test_db.py` in the `TestGetPostingsWithScores` class:

```python
def test_search_by_title(self, tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Senior Engineer",
            title_hash="srch1",
            url="https://example.com/srch1",
        )
    )
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Product Manager",
            title_hash="srch2",
            url="https://example.com/srch2",
        )
    )
    results = db.get_postings_with_scores(search="engineer")
    assert len(results) == 1
    assert results[0]["title"] == "Senior Engineer"

def test_search_by_description(self, tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Role A",
            title_hash="srch3",
            url="https://example.com/srch3",
            description="Build data pipelines using Python",
        )
    )
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Role B",
            title_hash="srch4",
            url="https://example.com/srch4",
            description="Manage product roadmap",
        )
    )
    results = db.get_postings_with_scores(search="python")
    assert len(results) == 1
    assert results[0]["title"] == "Role A"

def test_search_case_insensitive(self, tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="SENIOR ENGINEER",
            title_hash="srch5",
            url="https://example.com/srch5",
        )
    )
    results = db.get_postings_with_scores(search="engineer")
    assert len(results) == 1

def test_search_no_results(self, tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Engineer",
            title_hash="srch6",
            url="https://example.com/srch6",
        )
    )
    results = db.get_postings_with_scores(search="zookeeper")
    assert len(results) == 0

def test_search_with_status_filter(self, tmp_path):
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    pid1 = db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Data Engineer",
            title_hash="srch7",
            url="https://example.com/srch7",
        )
    )
    pid2 = db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Data Manager",
            title_hash="srch8",
            url="https://example.com/srch8",
        )
    )
    db.update_posting_status(pid2, "applied")
    results = db.get_postings_with_scores(status="new", search="data")
    assert len(results) == 1
    assert results[0]["title"] == "Data Engineer"

def test_search_special_characters(self, tmp_path):
    """LIKE wildcards % and _ in search terms should be escaped."""
    db = init_db(tmp_path / "test.db")
    company = Company(name="Acme Corp")
    cid = db.insert_company(company)
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="100% Remote",
            title_hash="srch9",
            url="https://example.com/srch9",
        )
    )
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Senior Engineer",
            title_hash="srch10",
            url="https://example.com/srch10",
        )
    )
    # Searching for "100%" should match only "100% Remote", not everything
    results = db.get_postings_with_scores(search="100%")
    assert len(results) == 1
    assert results[0]["title"] == "100% Remote"

def test_search_empty_string_no_filter(self, tmp_path):
    """Empty search string should return all postings (no filter)."""
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Engineer",
            title_hash="srch11",
            url="https://example.com/srch11",
        )
    )
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Manager",
            title_hash="srch12",
            url="https://example.com/srch12",
        )
    )
    results = db.get_postings_with_scores(search="")
    assert len(results) == 2

def test_search_none_no_filter(self, tmp_path):
    """None search should return all postings (backward compatible)."""
    db = init_db(tmp_path / "test.db")
    company = Company(name="TestCorp")
    cid = db.insert_company(company)
    db.insert_posting(
        JobPosting(
            company_id=cid,
            title="Engineer",
            title_hash="srch13",
            url="https://example.com/srch13",
        )
    )
    results = db.get_postings_with_scores(search=None)
    assert len(results) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/kurtt/job-search && python -m pytest tests/test_db.py::TestGetPostingsWithScores::test_search_by_title tests/test_db.py::TestGetPostingsWithScores::test_search_by_description tests/test_db.py::TestGetPostingsWithScores::test_search_case_insensitive tests/test_db.py::TestGetPostingsWithScores::test_search_no_results tests/test_db.py::TestGetPostingsWithScores::test_search_with_status_filter tests/test_db.py::TestGetPostingsWithScores::test_search_special_characters tests/test_db.py::TestGetPostingsWithScores::test_search_empty_string_no_filter tests/test_db.py::TestGetPostingsWithScores::test_search_none_no_filter -v
```

Expected: FAIL (TypeError: `get_postings_with_scores()` got unexpected keyword argument `search`)

- [ ] **Step 3: Implement the `search` parameter**

Add `search: str | None = None` to `get_postings_with_scores()` signature in `quarry/store/db.py`. After the status filter and before the ORDER BY clause, add:

```python
# Keyword search filter
if search:
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    stmt = stmt.where(
        or_(
            ORMPosting.title.ilike(f"%{escaped}%", escape="\\"),
            ORMPosting.description.ilike(f"%{escaped}%", escape="\\"),
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/kurtt/job-search && python -m pytest tests/test_db.py::TestGetPostingsWithScores -v
```

Expected: All search tests PASS. All existing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add quarry/store/db.py tests/test_db.py
git commit -m "feat: add search parameter to get_postings_with_scores()"
```

---

### Task 2: Add `get_user_setting()` convenience method

**Files:**
- Modify: `quarry/store/db.py` (add method after `get_user_settings_raw`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing test**

Add a new test class in `tests/test_db.py`:

```python
class TestGetUserSetting:
    def test_returns_existing_value(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        db.save_user_setting(1, "labels_since_last_train", "42")
        assert db.get_user_setting(1, "labels_since_last_train") == "42"

    def test_returns_none_for_missing_key(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        assert db.get_user_setting(1, "nonexistent") is None

    def test_returns_none_for_null_value(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        # Insert a setting with NULL value directly
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute(
            "INSERT INTO user_settings (user_id, key, value) VALUES (?, ?, NULL)",
            (1, "test_key"),
        )
        conn.commit()
        conn.close()
        assert db.get_user_setting(1, "test_key") is None

    def test_preserves_empty_string(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        db.save_user_setting(1, "test_key", "")
        assert db.get_user_setting(1, "test_key") == ""
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/kurtt/job-search && python -m pytest tests/test_db.py::TestGetUserSetting -v
```

Expected: FAIL (AttributeError: 'Database' object has no attribute 'get_user_setting')

- [ ] **Step 3: Implement `get_user_setting()`**

Add in `quarry/store/db.py` after `get_user_settings_raw()`:

```python
def get_user_setting(self, user_id: int, key: str) -> str | None:
    """Get a single user setting value by key.

    Returns None for both missing keys and keys with NULL values.
    Preserves empty string values.
    """
    return self.get_user_settings_raw(user_id).get(key)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/kurtt/job-search && python -m pytest tests/test_db.py::TestGetUserSetting -v
```

Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add quarry/store/db.py tests/test_db.py
git commit -m "feat: add get_user_setting() convenience method"
```

---

### Task 3: Extract `train_classifier()` into shared module

**Files:**
- Create: `quarry/rank/train.py`
- Modify: `quarry/rank/__main__.py` (refactor `cmd_train` to call shared function)

- [ ] **Step 1: Create `quarry/rank/train.py`**

Create `quarry/rank/train.py` with `train_classifier(db, min_labels=5)` that extracts the core training logic from `cmd_train()`. The function should:

1. Get labels via `db.get_labels_with_postings(user_id=1)`
2. Deserialize embeddings, build posting-like objects
3. Call `ClassifierScorer.fit()`
4. Persist `ClassifierVersion` ORM row, save model pickle with absolute path
5. Deactivate prior versions
6. Reset `labels_since_last_train` and `retrain_pending` counters
7. Return a dict with `training_samples`, `cv_auc_mean`, `model_path`, and optionally `error`

```python
"""Shared classifier training logic for CLI and web UI."""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

from sqlalchemy import update

if TYPE_CHECKING:
    from quarry.store.db import Database

log = logging.getLogger(__name__)

_MODELS_DIR = Path(__file__).parent.parent / "models"


def train_classifier(
    db: Database,
    user_id: int = 1,
    min_labels: int = 5,
) -> dict:
    """Train classifier on labeled postings.

    Handles the full training lifecycle:
    1. Fetch labels and embeddings
    2. Fit logistic regression
    3. Persist ClassifierVersion ORM row
    4. Save model pickle (absolute path)
    5. Deactivate prior versions
    6. Reset counters

    Returns:
        dict with keys:
        - training_samples (int)
        - cv_auc_mean (float)
        - model_path (str)
        On failure, dict with key 'error' (str).
    """
    from quarry.pipeline.embedder import deserialize_embedding, get_embedding_dim
    from quarry.rank.scorers.classifier import ClassifierScorer
    from quarry.store.models import ClassifierVersion as ORMClsVersion
    from quarry.store.session import session_scope

    rows = db.get_labels_with_postings(user_id=user_id)
    if not rows:
        return {"error": "No labeled postings found. Label some postings first."}

    embeddings = []
    valid_labels = []
    dim = get_embedding_dim()

    for row in rows:
        label, emb_bytes, posting_id = row
        if emb_bytes is None:
            continue
        try:
            emb = deserialize_embedding(emb_bytes, dim)
        except (ValueError, TypeError):
            continue
        posting = SimpleNamespace(embedding=emb, id=posting_id)
        embeddings.append(posting)
        valid_labels.append(label)

    if len(valid_labels) < min_labels:
        return {
            "error": (
                f"Not enough labeled postings ({len(valid_labels)} < {min_labels}). "
                "Label more postings first."
            ),
            "training_samples": len(valid_labels),
        }

    scorer = ClassifierScorer(min_training_labels=min_labels)
    result = scorer.fit(valid_labels, embeddings)
    if result is None:
        return {"error": "Training failed — insufficient labels after filtering embeddings."}

    # Persist ClassifierVersion via ORM
    with session_scope(engine=db.engine) as session:
        version = ORMClsVersion(
            training_samples=result["training_samples"],
            positive_samples=result["positive_samples"],
            negative_samples=result["negative_samples"],
            cv_accuracy=result["cv_auc_mean"],
            cv_precision=None,
            cv_recall=None,
            active=True,
        )
        session.add(version)
        session.flush()
        version_id = version.id

        # Deactivate previous versions
        session.execute(
            update(ORMClsVersion)
            .where(ORMClsVersion.id != version_id)
            .values(active=False)
        )

        # Save model to disk using absolute path
        models_dir = _MODELS_DIR
        models_dir.mkdir(parents=True, exist_ok=True)
        model_path = models_dir / f"classifier_{user_id}_v{version_id}.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(scorer.model, f)
        version.model_path = str(model_path)

    # Reset the retrain counters
    db.save_user_setting(user_id, "labels_since_last_train", "0")
    db.save_user_setting(user_id, "retrain_pending", "false")

    return {
        "training_samples": result["training_samples"],
        "cv_auc_mean": result["cv_auc_mean"],
        "model_path": str(model_path),
    }
```

- [ ] **Step 2: Refactor `cmd_train()` in `quarry/rank/__main__.py`**

Replace the body of `cmd_train()` with a call to `train_classifier()`:

```python
def cmd_train(args):
    """Train classifier on current labels."""
    from quarry.rank.train import train_classifier

    db = _get_db()
    result = train_classifier(db=db, user_id=1, min_labels=args.min_labels)

    if "error" in result:
        print(result["error"])
        return

    print(f"Training complete. Model saved: {result['model_path']}")
    print(f"AUC: {result['cv_auc_mean']:.4f}, Samples: {result['training_samples']}")
```

- [ ] **Step 3: Run existing rank tests to verify nothing broke**

```bash
cd /home/kurtt/job-search && python -m pytest tests/test_rank_classifier.py tests/test_rank_pipeline.py tests/test_rank_scorers.py -v
```

Expected: All PASS (these tests don't call `cmd_train`).

- [ ] **Step 4: Verify CLI still works**

```bash
cd /home/kurtt/job-search && python -m quarry.rank train --min-labels 5 2>&1 | head -5
```

Expected: Either "Not enough labeled postings" or "Training complete" depending on DB state. No import errors or tracebacks.

- [ ] **Step 5: Commit**

```bash
git add quarry/rank/train.py quarry/rank/__main__.py
git commit -m "refactor: extract train_classifier() into shared module"
```

---

### Task 4: Add `app.secret_key` and flash message rendering

**Files:**
- Modify: `quarry/ui/app.py` (add `app.secret_key`)
- Modify: `quarry/ui/templates/base.html` (add flash block)

- [ ] **Step 1: Set `app.secret_key` in `quarry/ui/app.py`**

After `app.config["PER_PAGE"] = 20` in `create_app()`, add:

```python
import os
app.secret_key = os.environ.get("QUARRY_SECRET_KEY", os.urandom(24).hex())
```

Don't forget to add `import os` at the top of the file.

- [ ] **Step 2: Add flash message block to `quarry/ui/templates/base.html`**

Inside `<main>`, before `{% block content %}`, add:

```html
    <main>
        {% with messages = get_flashed_messages() %}
        {% if messages %}
        <div class="flash-messages">
            {% for message in messages %}
            <div class="flash-message">{{ message }}</div>
            {% endfor %}
        </div>
        {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </main>
```

- [ ] **Step 3: Add flash message CSS to `quarry/ui/static/style.css`**

```css
.flash-messages {
    margin-bottom: 1rem;
}

.flash-message {
    background: #d4edda;
    color: #155724;
    padding: 0.75rem 1rem;
    border-radius: 4px;
    margin-bottom: 0.5rem;
    border: 1px solid #c3e6cb;
}
```

- [ ] **Step 4: Verify no regressions**

```bash
cd /home/kurtt/job-search && python -m pytest tests/test_ui.py::TestFlaskApp::test_create_app -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quarry/ui/app.py quarry/ui/templates/base.html quarry/ui/static/style.css
git commit -m "feat: add app.secret_key and flash message rendering"
```

---

### Task 5: Add `POST /retrain` route

**Files:**
- Modify: `quarry/ui/routes.py` (add `flash` import, add retrain route, pass label count and search)
- Test: `tests/test_ui.py`

- [ ] **Step 1: Write failing tests for retrain route**

Add to `tests/test_ui.py`:

```python
class TestRetrainRoute:
    def test_retrain_insufficient_labels(self, app, tmp_path):
        """POST /retrain with no labels should flash an error."""
        client = app.test_client()
        response = client.post("/retrain", follow_redirects=True)
        assert response.status_code == 200
        # Should show error flash about insufficient labels
        assert b"Not enough" in response.data or b"No labeled" in response.data

    def test_retrain_redirects_to_postings(self, app):
        """POST /retrain should redirect back to /postings."""
        client = app.test_client()
        response = client.post("/retrain")
        assert response.status_code == 302
        assert "/postings" in response.headers["Location"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/kurtt/job-search && python -m pytest tests/test_ui.py::TestRetrainRoute -v
```

Expected: FAIL (404 or 405 for `/retrain`)

- [ ] **Step 3: Implement the retrain route**

In `quarry/ui/routes.py`:

1. Add `flash` to the Flask import line:
```python
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
```

2. Add the retrain route after the `label` route:

```python
@bp.route("/retrain", methods=["POST"])
def retrain():
    from quarry.rank.train import train_classifier

    db = get_db()
    return_status = request.form.get("return_status", "new")
    return_q = request.form.get("q", "")

    result = train_classifier(db=db, user_id=USER_ID, min_labels=5)

    if "error" in result:
        flash(result["error"])
    else:
        flash(
            f"Classifier trained on {result['training_samples']} labels "
            f"(AUC: {result['cv_auc_mean']:.2f})."
        )

    return redirect(url_for("ui.postings", status=return_status, q=return_q))
```

3. Update the `postings()` route to pass `search` and label count:

```python
@bp.route("/postings")
def postings():
    status = request.args.get("status", "new")
    if status not in VALID_STATUSES:
        status = "new"
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1
    q = request.args.get("q", "")

    db = get_db()
    per_page = current_app.config["PER_PAGE"]
    offset = (page - 1) * per_page

    results = db.get_postings_with_scores(
        user_id=USER_ID,
        status=status,
        limit=per_page + 1,
        offset=offset,
        search=q if q else None,
    )
    has_next = len(results) > per_page
    results = results[:per_page]

    counts = {
        s: db.count_postings_by_watchlist(user_id=USER_ID, status=s)
        for s in VALID_STATUSES
    }

    label_count = int(db.get_user_setting(USER_ID, "labels_since_last_train") or "0")

    return render_template(
        "postings.html",
        results=results,
        status=status,
        page=page,
        has_next=has_next,
        counts=counts,
        valid_statuses=VALID_STATUSES,
        q=q,
        label_count=label_count,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/kurtt/job-search && python -m pytest tests/test_ui.py::TestRetrainRoute -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quarry/ui/routes.py tests/test_ui.py
git commit -m "feat: add POST /retrain route and search param to postings"
```

---

### Task 6: Update postings template — score breakdown, search box, retrain button

**Files:**
- Modify: `quarry/ui/templates/postings.html`
- Modify: `quarry/ui/static/style.css`

- [ ] **Step 1: Update the template**

Replace the content of `quarry/ui/templates/postings.html` with the full updated template. Key changes:
1. Add search form between status tabs and card list
2. Replace the single score line with a score breakdown
3. Add retrain button in the header area
4. Add flash message rendering
5. Preserve search `q` in pagination links
6. Show "No results" messages differently for search vs. empty tab
7. Show role_tier and fit_reason as badges if present

<details>
<summary>Full template (click to expand)</summary>

```html
{% extends "base.html" %}
{% block title %}Postings — Quarry{% endblock %}
{% block content %}
<h1>Postings</h1>

<div class="toolbar">
  <div class="tabs">
    {% for s in valid_statuses %}
    <a
      href="{{ url_for('ui.postings', status=s) }}"
      class="{{ 'active' if s == status else '' }}"
    >
      {{ s.capitalize() }}
      <span class="count">({{ counts[s] }})</span>
    </a>
    {% endfor %}
  </div>
  <form method="POST" action="{{ url_for('ui.retrain') }}" class="inline retrain-form">
    <input type="hidden" name="return_status" value="{{ status }}" />
    <input type="hidden" name="q" value="{{ q }}" />
    <button type="submit" class="small btn-retrain" {% if label_count < 5 %}disabled title="Need at least 5 interest labels to train"{% endif %}>
      Retrain Classifier
    </button>
    <span class="label-count">{{ label_count }} interest label{{ 's' if label_count != 1 else '' }} since last train</span>
  </form>
</div>

<form method="GET" action="{{ url_for('ui.postings') }}" class="search-form">
  <input type="hidden" name="status" value="{{ status }}" />
  <input type="text" name="q" value="{{ q }}" placeholder="Search title or description..." class="search-input" />
  {% if q %}
  <a href="{{ url_for('ui.postings', status=status) }}" class="search-clear">Clear</a>
  {% endif %}
  <button type="submit" class="small">Search</button>
</form>

{% if results %}
{% for row in results %}
<div class="card">
  <div class="card-title">
    <a href="{{ row.url }}">{{ row.title }}</a>
  </div>
  <div class="card-meta">
    {{ row.company_name }} {% if row.location %} &middot; {{ row.location }}{% endif %} {% if row.work_model %}
    <span class="badge badge-{{ row.work_model }}">{{ row.work_model }}</span>
    {% endif %}
    <span class="badge badge-{{ row.status }}">{{ row.status }}</span>
    {% if row.role_tier %}
    <span class="badge badge-{{ row.role_tier }}">{{ row.role_tier }}</span>
    {% endif %}
  </div>
  <div class="card-meta score-line">
    {% if row.composite_score and row.composite_score > 0 %}
    <span class="score">Score: {{ "%.3f"|format(row.composite_score) }} (composite)</span>
    <span class="score-detail">classifier {{ "%.3f"|format(row.classifier_score or 0) }} &middot; similarity {{ "%.3f"|format(row.similarity_score or 0) }}{% if row.fit_score and row.fit_score != 0 %} &middot; fit {{ "+%d"|format(row.fit_score) if row.fit_score > 0 else row.fit_score }}{% endif %}</span>
    {% elif row.similarity_score and row.similarity_score > 0 %}
    <span class="score">similarity: {{ "%.3f"|format(row.similarity_score) }}</span>
    {% else %}
    <span class="score">no score</span>
    {% endif %}
    {% if row.fit_reason %}
    <span class="fit-reason">{{ row.fit_reason }}</span>
    {% endif %}
  </div>
  {% if row.description %}
  <details>
    <summary>Description</summary>
    <div class="description">{{ row.description }}</div>
  </details>
  {% endif %}
  <div class="card-actions">
    <form
      method="POST"
      action="{{ url_for('ui.label', posting_id=row.id) }}"
      class="inline"
    >
      <input type="hidden" name="signal" value="positive" />
      <button type="submit" class="small btn-positive">
        &#x1F44D; Interested
      </button>
    </form>
    <form
      method="POST"
      action="{{ url_for('ui.label', posting_id=row.id) }}"
      class="inline"
    >
      <input type="hidden" name="signal" value="negative" />
      <button type="submit" class="small btn-negative">
        &#x1F44E; Not Interested
      </button>
    </form>
    <form
      method="POST"
      action="{{ url_for('ui.label', posting_id=row.id) }}"
      class="inline"
    >
      <input type="hidden" name="status" value="applied" />
      <button type="submit" class="small btn-applied">Applied</button>
    </form>
    <form
      method="POST"
      action="{{ url_for('ui.label', posting_id=row.id) }}"
      class="inline"
    >
      <input type="hidden" name="status" value="archived" />
      <button type="submit" class="small btn-archive">Archive</button>
    </form>
  </div>
</div>
{% endfor %}

<div class="pagination">
  {% if page > 1 %}
  <a href="{{ url_for('ui.postings', status=status, page=page-1, q=q) }}"
    >&laquo; Prev</a
  >
  {% endif %}
  <span class="current">Page {{ page }}</span>
  {% if has_next %}
  <a href="{{ url_for('ui.postings', status=status, page=page+1, q=q) }}"
    >Next &raquo;</a
  >
  {% endif %}
</div>
{% elif q %}
<p>No postings match &ldquo;{{ q }}&rdquo;.</p>
{% else %}
<p>No postings with status &ldquo;{{ status }}&rdquo; found.</p>
{% endif %} {% endblock %}
```

</details>

- [ ] **Step 2: Add CSS for new elements**

Add to `quarry/ui/static/style.css`:

```css
.toolbar {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 0.5rem;
}

.retrain-form {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.btn-retrain {
    background: #007bff;
    color: #fff;
}

.btn-retrain:hover:not(:disabled) {
    background: #0056b3;
}

.btn-retrain:disabled {
    background: #ccc;
    color: #666;
    cursor: not-allowed;
}

.label-count {
    font-size: 0.8rem;
    color: #999;
}

.search-form {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 1rem;
}

.search-input {
    flex: 1;
    padding: 0.4rem 0.6rem;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 0.9rem;
}

.search-input:focus {
    outline: none;
    border-color: #007bff;
}

.search-clear {
    font-size: 0.85rem;
    color: #999;
    text-decoration: none;
}

.search-clear:hover {
    color: #333;
}

.score-line {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
}

.score-detail {
    font-size: 0.75rem;
    color: #999;
}

.fit-reason {
    font-size: 0.75rem;
    color: #666;
    font-style: italic;
}

.badge-reach {
    background: #fff3cd;
    color: #856404;
}

.badge-match {
    background: #d4edda;
    color: #155724;
}

.badge-strong-match {
    background: #28a745;
    color: #fff;
}
```

- [ ] **Step 3: Verify UI renders**

```bash
cd /home/kurtt/job-search && python -m quarry.ui &
sleep 3
curl -s http://localhost:5000/postings | head -50
# Kill the server
kill %1
```

Expected: HTML output shows search box, retrain button, and score breakdown structure.

- [ ] **Step 4: Run all UI tests**

```bash
cd /home/kurtt/job-search && python -m pytest tests/test_ui.py -v
```

Expected: All pass (the skip markers for Phase 4 routes remain; new tests should pass).

- [ ] **Step 5: Commit**

```bash
git add quarry/ui/templates/postings.html quarry/ui/static/style.css
git commit -m "feat: score breakdown, search box, retrain button in postings UI"
```

---

### Task 7: Run full test suite and lint

- [ ] **Step 1: Run full test suite**

```bash
cd /home/kurtt/job-search && python -m pytest tests/ -q
```

Expected: All pass, 0 failures. (The pre-existing `test_add_company_with_domain` flaky event-loop test may still fail — that's a known issue.)

- [ ] **Step 2: Run linter and type checker**

```bash
cd /home/kurtt/job-search && ruff check . && PYTHONPATH=/home/kurtt/job-search pyright quarry/
```

Expected: Clean (no errors).

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: lint and type fixes from full test run"
```

---

### Task 8: Update STATUS.md

- [ ] **Step 1: Update `docs/STATUS.md`**

Add to the "M5: Ranking pipeline" section:
- [x] Score breakdown display in UI (composite/classifier/similarity/fit)
- [x] Keyword search in postings UI
- [x] Retrain classifier button in UI
- [x] `train_classifier()` shared module
- [x] Flash message support in base template

Add to Verification section:
- `python -m quarry.rank train` — shared `train_classifier()` function
- UI: search box, retrain button, score breakdown on `/postings`
- `POST /retrain` — triggers classifier training with flash feedback

- [ ] **Step 2: Commit**

```bash
git add docs/STATUS.md
git commit -m "docs: update STATUS.md with UI enhancements"
```