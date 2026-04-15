# M8: Labeling UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal Flask web UI to view, label, and manage job postings — the human feedback loop that closes the Quarry cycle.

**Architecture:** Single-user Flask app with server-rendered HTML templates (no JS framework). Uses existing `Database` class directly for reads/writes. Adds new DB methods for pagination, status updates, label reads, and agent action reads. Four routes: postings list with status filter tabs, label action, company watchlist, and agent log viewer. Runs via `python -m quarry.ui`.

**Tech Stack:** Python 3.11, Flask 3.0+ (already in `pyproject.toml`), SQLite via existing `quarry.store.db.Database`, Jinja2 templates, plain CSS

---

## File Structure

| File | Purpose |
|------|---------|
| `quarry/ui/__init__.py` | Package init |
| `quarry/ui/app.py` | Flask app factory, route handlers, `create_app()` |
| `quarry/ui/__main__.py` | CLI entrypoint: `python -m quarry.ui` |
| `quarry/ui/templates/base.html` | Base layout with nav, shared CSS |
| `quarry/ui/templates/postings.html` | Paginated postings list with status tabs |
| `quarry/ui/templates/companies.html` | Company watchlist view |
| `quarry/ui/templates/log.html` | Agent action log (read-only) |
| `quarry/ui/static/style.css` | Minimal CSS stylesheet |
| `quarry/store/db.py` | Add: `get_posting_by_id`, `update_posting_status`, `count_postings`, `get_postings_paginated`, `get_labels_for_posting`, `get_agent_actions` |
| `tests/test_ui.py` | Tests for Flask routes and DB methods |

---

## Task 1: Add DB helper methods for the UI

The UI needs several DB methods that don't exist yet. We add them to `quarry/store/db.py` and test them.

**Files:**
- Modify: `quarry/store/db.py`
- Test: `tests/test_ui.py`

- [ ] **Step 1: Write tests for new DB methods**

Create `tests/test_ui.py` with tests for all new DB methods. We'll use the existing `tmp_path` + `init_db` pattern.

```python
import pytest
from datetime import datetime, timezone

from quarry.models import Company, JobPosting, Label, AgentAction
from quarry.store.db import Database, init_db


@pytest.fixture
def db(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def db_with_postings(db):
    company = Company(name="TestCorp", ats_type="greenhouse", ats_slug="testcorp")
    cid = db.insert_company(company)
    for i in range(5):
        posting = JobPosting(
            company_id=cid,
            title=f"Senior Analyst {i}",
            title_hash=f"hash_ui_{i}",
            url=f"https://example.com/job/{i}",
            description=f"Great analytics role {i}",
            location="Remote, US",
            work_model="remote",
            similarity_score=0.8 - i * 0.05,
            source_type="greenhouse",
        )
        db.insert_posting(posting)
    return db


class TestGetPostingById:
    def test_returns_posting_when_found(self, db_with_postings):
        all_postings = db_with_postings.get_postings(limit=10)
        pid = all_postings[0].id
        result = db_with_postings.get_posting_by_id(pid)
        assert result is not None
        assert result.id == pid
        assert result.title == all_postings[0].title

    def test_returns_none_when_not_found(self, db):
        result = db.get_posting_by_id(9999)
        assert result is None


class TestUpdatePostingStatus:
    def test_updates_status(self, db_with_postings):
        all_postings = db_with_postings.get_postings(limit=10)
        pid = all_postings[0].id
        db_with_postings.update_posting_status(pid, "applied")
        updated = db_with_postings.get_posting_by_id(pid)
        assert updated.status == "applied"

    def test_does_not_affect_other_postings(self, db_with_postings):
        all_postings = db_with_postings.get_postings(limit=10)
        db_with_postings.update_posting_status(all_postings[0].id, "applied")
        other = db_with_postings.get_posting_by_id(all_postings[1].id)
        assert other.status == "new"


class TestCountPostings:
    def test_counts_all_postings(self, db_with_postings):
        count = db_with_postings.count_postings()
        assert count == 5

    def test_counts_by_status(self, db_with_postings):
        all_postings = db_with_postings.get_postings(limit=10)
        db_with_postings.update_posting_status(all_postings[0].id, "applied")
        assert db_with_postings.count_postings(status="new") == 4
        assert db_with_postings.count_postings(status="applied") == 1

    def test_counts_zero_when_empty(self, db):
        assert db.count_postings() == 0


class TestGetPostingsPaginated:
    def test_returns_postings_with_company_name(self, db_with_postings):
        results = db_with_postings.get_postings_paginated(status="new", limit=10, offset=0)
        assert len(results) == 5
        posting, company_name = results[0]
        assert company_name == "TestCorp"
        assert posting.title.startswith("Senior Analyst")

    def test_pagination_offset_and_limit(self, db_with_postings):
        page1 = db_with_postings.get_postings_paginated(status="new", limit=2, offset=0)
        page2 = db_with_postings.get_postings_paginated(status="new", limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        ids_page1 = {p.id for p, _ in page1}
        ids_page2 = {p.id for p, _ in page2}
        assert ids_page1.isdisjoint(ids_page2)

    def test_sorted_by_similarity_desc(self, db_with_postings):
        results = db_with_postings.get_postings_paginated(status="new", limit=10, offset=0)
        scores = [p.similarity_score for p, _ in results]
        assert scores == sorted(scores, reverse=True)

    def test_returns_empty_when_no_match(self, db_with_postings):
        results = db_with_postings.get_postings_paginated(status="applied", limit=10, offset=0)
        assert results == []


class TestGetLabelsForPosting:
    def test_returns_labels(self, db_with_postings):
        all_postings = db_with_postings.get_postings(limit=10)
        pid = all_postings[0].id
        label = Label(posting_id=pid, signal="positive", notes="Great fit")
        db_with_postings.insert_label(label)
        labels = db_with_postings.get_labels_for_posting(pid)
        assert len(labels) == 1
        assert labels[0].signal == "positive"
        assert labels[0].notes == "Great fit"

    def test_returns_empty_when_no_labels(self, db_with_postings):
        all_postings = db_with_postings.get_postings(limit=10)
        pid = all_postings[0].id
        labels = db_with_postings.get_labels_for_posting(pid)
        assert labels == []


class TestGetAgentActions:
    def test_returns_recent_actions(self, db):
        action = AgentAction(
            run_id="test-run", tool_name="add_company", tool_args='{"name": "Foo"}',
            tool_result="Added", rationale="Test"
        )
        db.insert_agent_action(action)
        actions = db.get_agent_actions(limit=10)
        assert len(actions) == 1
        assert actions[0].tool_name == "add_company"

    def test_respects_limit(self, db):
        for i in range(5):
            action = AgentAction(
                run_id="test-run", tool_name="test", tool_args=f'{{"i": {i}}}',
            )
            db.insert_agent_action(action)
        actions = db.get_agent_actions(limit=3)
        assert len(actions) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui.py -v`
Expected: FAIL — methods don't exist yet.

- [ ] **Step 3: Add `get_posting_by_id` method to `quarry/store/db.py`**

Add after the `posting_exists_by_url` method (around line 187):

```python
    def get_posting_by_id(self, posting_id: int) -> models.JobPosting | None:
        """Get a single posting by ID.

        Args:
            posting_id: ID of the posting to retrieve.

        Returns:
            JobPosting if found, None otherwise.
        """
        sql = "SELECT * FROM job_postings WHERE id = ?"
        rows = self.execute(sql, (posting_id,))
        if rows:
            return models.JobPosting(**dict(rows[0]))
        return None
```

- [ ] **Step 4: Add `update_posting_status` method to `quarry/store/db.py`**

Add after `mark_postings_seen` (around line 346):

```python
    def update_posting_status(self, posting_id: int, status: str) -> None:
        """Update the status of a posting.

        Args:
            posting_id: ID of the posting to update.
            status: New status value (new, seen, applied, rejected, archived).
        """
        sql = "UPDATE job_postings SET status = ? WHERE id = ?"
        self.execute(sql, (status, posting_id))
```

- [ ] **Step 5: Add `count_postings` method to `quarry/store/db.py`**

Add after `update_posting_status`:

```python
    def count_postings(self, status: str | None = None) -> int:
        """Count postings, optionally filtered by status.

        Args:
            status: If set, count only postings with this status.

        Returns:
            Count of matching postings.
        """
        sql = "SELECT COUNT(*) FROM job_postings"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        rows = self.execute(sql, params)
        return rows[0][0] if rows else 0
```

- [ ] **Step 6: Add `get_postings_paginated` method to `quarry/store/db.py`**

Add after `count_postings`:

```python
    def get_postings_paginated(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        threshold: float | None = None,
    ) -> list[tuple[models.JobPosting, str]]:
        """Get postings paginated with company names, sorted by similarity.

        Args:
            status: Filter by posting status. None returns all.
            limit: Max results per page.
            offset: Number of results to skip.
            threshold: Minimum similarity score. If None, returns all.

        Returns:
            List of (JobPosting, company_name) tuples sorted by similarity_score DESC.
        """
        sql = """
            SELECT p.*, c.name as company_name
            FROM job_postings p
            JOIN companies c ON p.company_id = c.id
        """
        conditions = []
        params: list = []
        if status:
            conditions.append("p.status = ?")
            params.append(status)
        if threshold is not None:
            conditions.append("p.similarity_score >= ?")
            params.append(threshold)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY p.similarity_score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self.execute(sql, tuple(params))
        results = []
        for row in rows:
            row_dict = dict(row)
            company_name = row_dict.pop("company_name")
            posting = models.JobPosting(**row_dict)
            results.append((posting, company_name))
        return results
```

- [ ] **Step 7: Add `get_labels_for_posting` method to `quarry/store/db.py`**

Add after `insert_label` (around line 243):

```python
    def get_labels_for_posting(self, posting_id: int) -> list[models.Label]:
        """Get all labels for a posting.

        Args:
            posting_id: ID of the posting.

        Returns:
            List of Label objects for the posting.
        """
        sql = "SELECT * FROM labels WHERE posting_id = ? ORDER BY labeled_at DESC"
        rows = self.execute(sql, (posting_id,))
        return [models.Label(**dict(row)) for row in rows]
```

- [ ] **Step 8: Add `get_agent_actions` method to `quarry/store/db.py`**

Add after `insert_agent_action` (around line 308):

```python
    def get_agent_actions(self, limit: int = 50) -> list[models.AgentAction]:
        """Get recent agent actions.

        Args:
            limit: Maximum number of actions to return.

        Returns:
            List of AgentAction objects ordered by created_at DESC.
        """
        sql = "SELECT * FROM agent_actions ORDER BY created_at DESC LIMIT ?"
        rows = self.execute(sql, (limit,))
        return [models.AgentAction(**dict(row)) for row in rows]
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui.py -v`
Expected: All tests PASS.

- [ ] **Step 10: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS (existing + new).

- [ ] **Step 11: Commit**

```bash
git add quarry/store/db.py tests/test_ui.py
git commit -m "feat(ui): add DB helper methods for labeling UI"
```

---

## Task 2: Create Flask app factory and base template

Set up the Flask application with `create_app()` pattern and the base HTML template with navigation and CSS.

**Files:**
- Create: `quarry/ui/__init__.py`
- Create: `quarry/ui/app.py`
- Create: `quarry/ui/templates/base.html`
- Create: `quarry/ui/static/style.css`
- Test: `tests/test_ui.py` (add app fixture and basic route tests)

- [ ] **Step 1: Write tests for Flask app creation and routes**

Add to `tests/test_ui.py` (append after existing test classes):

```python
import pytest
from quarry.ui.app import create_app


@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "test.db")
    from quarry.store.db import init_db
    init_db(db_path)
    app = create_app(db_path=db_path)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def app_with_postings(app, tmp_path):
    from quarry.store.db import Database
    db = Database(tmp_path / "test.db")
    company = Company(name="Acme Corp", ats_type="greenhouse", ats_slug="acme")
    cid = db.insert_company(company)
    for i in range(3):
        posting = JobPosting(
            company_id=cid,
            title=f"Data Engineer {i}",
            title_hash=f"hash_route_{i}",
            url=f"https://acme.com/job/{i}",
            description="Build data pipelines",
            location="Remote, US",
            work_model="remote",
            similarity_score=0.75 - i * 0.1,
            source_type="greenhouse",
        )
        db.insert_posting(posting)
    return app


class TestFlaskApp:
    def test_create_app(self, app):
        assert app is not None

    def test_home_redirects_to_postings(self, client):
        response = client.get("/")
        assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui.py::TestFlaskApp -v`
Expected: FAIL — `quarry.ui.app` module doesn't exist.

- [ ] **Step 3: Create `quarry/ui/__init__.py`**

```python
```

(Empty init file, following project convention.)

- [ ] **Step 4: Create `quarry/ui/app.py` with Flask app factory**

```python
from flask import Flask

from quarry.store.db import Database


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    if db_path is None:
        from quarry.config import settings
        db_path = settings.db_path

    db = Database(db_path)
    app.config["DB"] = db
    app.config["PER_PAGE"] = 20

    from quarry.ui.routes import bp
    app.register_blueprint(bp)

    return app
```

- [ ] **Step 5: Create `quarry/ui/routes.py` with route blueprint**

```python
from flask import Blueprint, redirect, url_for

bp = Blueprint("ui", __name__, template_folder="templates")


def get_db():
    from flask import current_app
    return current_app.config["DB"]


@bp.route("/")
def index():
    return redirect(url_for("ui.postings"))
```

- [ ] **Step 6: Create `quarry/ui/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% block title %}Quarry{% endblock %}</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
    <nav>
        <a href="{{ url_for('ui.postings') }}">Postings</a>
        <a href="{{ url_for('ui.companies') }}">Companies</a>
        <a href="{{ url_for('ui.log') }}">Agent Log</a>
    </nav>
    <main>
        {% block content %}{% endblock %}
    </main>
</body>
</html>
```

- [ ] **Step 7: Create `quarry/ui/static/style.css`**

```css
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 1rem;
    background: #f8f8f8;
    color: #333;
}
nav {
    padding: 0.75rem 0;
    margin-bottom: 1rem;
    border-bottom: 1px solid #ddd;
}
nav a {
    margin-right: 1rem;
    text-decoration: none;
    color: #0066cc;
}
nav a:hover {
    text-decoration: underline;
}
h1, h2, h3 {
    margin-top: 0;
}
.card {
    background: white;
    border: 1px solid #ddd;
    border-radius: 6px;
    padding: 1rem;
    margin-bottom: 0.75rem;
}
.card-title {
    font-size: 1.1rem;
    font-weight: 600;
    margin: 0 0 0.25rem 0;
}
.card-meta {
    font-size: 0.85rem;
    color: #666;
    margin: 0.25rem 0;
}
.badge {
    display: inline-block;
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    border-radius: 3px;
    font-weight: 600;
}
.badge-remote { background: #d4edda; color: #155724; }
.badge-hybrid { background: #fff3cd; color: #856404; }
.badge-onsite { background: #cce5ff; color: #004085; }
.badge-new { background: #d4edda; color: #155724; }
.badge-seen { background: #e2e3e5; color: #383d41; }
.badge-applied { background: #cce5ff; color: #004085; }
.badge-rejected { background: #f8d7da; color: #721c24; }
.badge-archived { background: #d6d8db; color: #1b1e21; }
.tabs {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
    border-bottom: 1px solid #ddd;
    padding-bottom: 0.5rem;
}
.tabs a {
    padding: 0.4rem 0.75rem;
    text-decoration: none;
    border-radius: 4px;
    color: #555;
    font-size: 0.9rem;
}
.tabs a.active {
    background: #0066cc;
    color: white;
}
.tabs a:hover:not(.active) {
    background: #eee;
}
.score {
    font-family: monospace;
    font-size: 0.85rem;
    color: #555;
}
.pagination {
    display: flex;
    gap: 0.5rem;
    margin-top: 1rem;
}
.pagination a, .pagination span {
    padding: 0.4rem 0.75rem;
    border: 1px solid #ddd;
    border-radius: 4px;
    text-decoration: none;
    color: #0066cc;
}
.pagination .current {
    background: #0066cc;
    color: white;
    border-color: #0066cc;
}
form.inline {
    display: inline;
}
button.small {
    font-size: 0.8rem;
    padding: 0.25rem 0.5rem;
    border: 1px solid #ccc;
    border-radius: 3px;
    cursor: pointer;
    background: white;
}
button.btn-positive { background: #d4edda; color: #155724; border-color: #c3e6cb; }
button.btn-negative { background: #f8d7da; color: #721c24; border-color: #f5c6cb; }
button.btn-applied { background: #cce5ff; color: #004085; border-color: #b8daff; }
button.btn-archive { background: #d6d8db; color: #1b1e21; border-color: #c6c8ca; }
details {
    margin-top: 0.5rem;
}
details summary {
    cursor: pointer;
    font-size: 0.85rem;
    color: #0066cc;
}
.description {
    max-height: 300px;
    overflow-y: auto;
    font-size: 0.85rem;
    white-space: pre-wrap;
    margin-top: 0.5rem;
    padding: 0.5rem;
    background: #fafafa;
    border-radius: 3px;
}
table {
    width: 100%;
    border-collapse: collapse;
}
th, td {
    text-align: left;
    padding: 0.5rem;
    border-bottom: 1px solid #ddd;
}
th {
    font-size: 0.85rem;
    color: #666;
}
.count {
    font-size: 0.8rem;
    color: #888;
}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui.py::TestFlaskApp -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add quarry/ui/__init__.py quarry/ui/app.py quarry/ui/routes.py quarry/ui/templates/base.html quarry/ui/static/style.css tests/test_ui.py
git commit -m "feat(ui): scaffold Flask app with base template and CSS"
```

---

## Task 3: Postings list route (GET /postings)

The main view: paginated list of postings with status filter tabs, sorted by similarity score.

**Files:**
- Modify: `quarry/ui/routes.py`
- Create: `quarry/ui/templates/postings.html`
- Test: `tests/test_ui.py` (add route tests)

- [ ] **Step 1: Write tests for postings route**

Add to `tests/test_ui.py` (inside `TestFlaskApp` class, or as a new class):

```python
class TestPostingsRoute:
    def test_postings_page_renders(self, app_with_postings):
        client = app_with_postings.test_client()
        response = client.get("/postings")
        assert response.status_code == 200
        assert b"Data Engineer" in response.data

    def test_postings_filtered_by_status(self, app_with_postings, tmp_path):
        from quarry.store.db import Database
        db = Database(tmp_path / "test.db")
        postings = db.get_postings(limit=10)
        db.update_posting_status(postings[0].id, "applied")
        client = app_with_postings.test_client()
        response = client.get("/postings?status=applied")
        assert response.status_code == 200
        assert b"Data Engineer 0" in response.data

    def test_postings_empty(self, app):
        client = app.test_client()
        response = client.get("/postings")
        assert response.status_code == 200
        assert b"No postings" in response.data

    def test_posting_counts_in_page(self, app_with_postings):
        client = app_with_postings.test_client()
        response = client.get("/postings")
        assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui.py::TestPostingsRoute -v`
Expected: FAIL — route not defined yet.

- [ ] **Step 3: Add `count_postings` to the app context**

Update `quarry/ui/routes.py` to add the postings route:

```python
from flask import Blueprint, current_app, redirect, render_template, request, url_for

from quarry.store.db import Database

bp = Blueprint("ui", __name__, template_folder="templates")

VALID_STATUSES = ["new", "seen", "applied", "rejected", "archived"]


def get_db() -> Database:
    return current_app.config["DB"]


@bp.route("/")
def index():
    return redirect(url_for("ui.postings"))


@bp.route("/postings")
def postings():
    status = request.args.get("status", "new")
    if status not in VALID_STATUSES:
        status = "new"
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    db = get_db()
    per_page = current_app.config["PER_PAGE"]
    offset = (page - 1) * per_page

    results = db.get_postings_paginated(
        status=status, limit=per_page + 1, offset=offset
    )
    has_next = len(results) > per_page
    results = results[:per_page]

    counts = {s: db.count_postings(status=s) for s in VALID_STATUSES}

    return render_template(
        "postings.html",
        results=results,
        status=status,
        page=page,
        has_next=has_next,
        counts=counts,
        valid_statuses=VALID_STATUSES,
    )
```

- [ ] **Step 4: Create `quarry/ui/templates/postings.html`**

```html
{% extends "base.html" %}
{% block title %}Postings — Quarry{% endblock %}
{% block content %}
<h1>Postings</h1>

<div class="tabs">
    {% for s in valid_statuses %}
    <a href="{{ url_for('ui.postings', status=s) }}"
       class="{{ 'active' if s == status else '' }}">
        {{ s.capitalize() }}
        <span class="count">({{ counts[s] }})</span>
    </a>
    {% endfor %}
</div>

{% if results %}
    {% for posting, company_name in results %}
    <div class="card">
        <div class="card-title">
            <a href="{{ posting.url }}">{{ posting.title }}</a>
        </div>
        <div class="card-meta">
            {{ company_name }}
            {% if posting.location %} &middot; {{ posting.location }}{% endif %}
            {% if posting.work_model %}
            <span class="badge badge-{{ posting.work_model }}">{{ posting.work_model }}</span>
            {% endif %}
            <span class="badge badge-{{ posting.status }}">{{ posting.status }}</span>
        </div>
        <div class="card-meta">
            <span class="score">score: {{ "%.3f"|format(posting.similarity_score or 0) }}</span>
        </div>
        {% if posting.description %}
        <details>
            <summary>Description</summary>
            <div class="description">{{ posting.description }}</div>
        </details>
        {% endif %}
        <form method="POST" action="{{ url_for('ui.label', posting_id=posting.id) }}" class="inline">
            <input type="hidden" name="status" value="applied">
            <button type="submit" class="small btn-applied">Applied</button>
        </form>
        <form method="POST" action="{{ url_for('ui.label', posting_id=posting.id) }}" class="inline">
            <input type="hidden" name="status" value="rejected">
            <button type="submit" class="small btn-negative">Pass</button>
        </form>
        <form method="POST" action="{{ url_for('ui.label', posting_id=posting.id) }}" class="inline">
            <input type="hidden" name="status" value="archived">
            <button type="submit" class="small btn-archive">Archive</button>
        </form>
    </div>
    {% endfor %}

    <div class="pagination">
        {% if page > 1 %}
        <a href="{{ url_for('ui.postings', status=status, page=page-1) }}">&laquo; Prev</a>
        {% endif %}
        <span class="current">Page {{ page }}</span>
        {% if has_next %}
        <a href="{{ url_for('ui.postings', status=status, page=page+1) }}">Next &raquo;</a>
        {% endif %}
    </div>
{% else %}
    <p>No postings with status "{{ status }}" found.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui.py::TestPostingsRoute -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quarry/ui/routes.py quarry/ui/templates/postings.html tests/test_ui.py
git commit -m "feat(ui): postings list route with status tabs and pagination"
```

---

## Task 4: Label route (POST /label/<posting_id>)

Handles form submissions to update posting status and add a label.

**Files:**
- Modify: `quarry/ui/routes.py`
- Test: `tests/test_ui.py` (add label route tests)

- [ ] **Step 1: Write tests for label route**

Add to `tests/test_ui.py`:

```python
class TestLabelRoute:
    def test_label_updates_status(self, app_with_postings, tmp_path):
        from quarry.store.db import Database
        db = Database(tmp_path / "test.db")
        postings = db.get_postings(limit=10)
        pid = postings[0].id
        client = app_with_postings.test_client()
        response = client.post(f"/label/{pid}", data={"status": "applied"})
        assert response.status_code == 302
        updated = db.get_posting_by_id(pid)
        assert updated.status == "applied"

    def test_label_creates_label_record(self, app_with_postings, tmp_path):
        from quarry.store.db import Database
        db = Database(tmp_path / "test.db")
        postings = db.get_postings(limit=10)
        pid = postings[0].id
        client = app_with_postings.test_client()
        client.post(f"/label/{pid}", data={"status": "applied", "notes": "Great fit"})
        labels = db.get_labels_for_posting(pid)
        assert len(labels) == 1
        assert labels[0].signal == "applied"
        assert labels[0].notes == "Great fit"

    def test_label_rejects_invalid_status(self, app_with_postings, tmp_path):
        from quarry.store.db import Database
        db = Database(tmp_path / "test.db")
        postings = db.get_postings(limit=10)
        pid = postings[0].id
        client = app_with_postings.test_client()
        response = client.post(f"/label/{pid}", data={"status": "invalid"})
        assert response.status_code == 400
        updated = db.get_posting_by_id(pid)
        assert updated.status == "new"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui.py::TestLabelRoute -v`
Expected: FAIL — route not defined yet.

- [ ] **Step 3: Add label route to `quarry/ui/routes.py`**

Add the import for `Label` model and the label route. Append to the imports at top:

```python
from quarry.models import Label
```

Add the route:

```python
VALID_SIGNALS = {"applied": "applied", "rejected": "negative", "seen": "negative", "archived": "skip"}


@bp.route("/label/<int:posting_id>", methods=["POST"])
def label(posting_id):
    status = request.form.get("status", "")
    if status not in VALID_STATUSES:
        return "Invalid status", 400

    db = get_db()
    posting = db.get_posting_by_id(posting_id)
    if posting is None:
        return "Posting not found", 404

    db.update_posting_status(posting_id, status)

    notes = request.form.get("notes", "").strip()
    signal = VALID_SIGNALS.get(status, "skip")
    label = Label(
        posting_id=posting_id,
        signal=signal,
        notes=notes or None,
        label_source="user",
    )
    db.insert_label(label)

    return redirect(url_for("ui.postings", status=request.args.get("return_status", "new")))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui.py::TestLabelRoute -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/ui/routes.py tests/test_ui.py
git commit -m "feat(ui): label route to update posting status and create label"
```

---

## Task 5: Companies route (GET /companies, POST /companies/<id>/toggle)

View the company watchlist and toggle companies active/inactive.

**Files:**
- Modify: `quarry/ui/routes.py`
- Create: `quarry/ui/templates/companies.html`
- Test: `tests/test_ui.py` (add companies route tests)

- [ ] **Step 1: Write tests for companies routes**

Add to `tests/test_ui.py`:

```python
class TestCompaniesRoute:
    def test_companies_list(self, app, tmp_path):
        from quarry.store.db import Database
        db = Database(tmp_path / "test.db")
        db.insert_company(Company(name="Alpha", ats_type="greenhouse", ats_slug="alpha"))
        db.insert_company(Company(name="Beta", ats_type="lever", ats_slug="beta", active=False))
        client = app.test_client()
        response = client.get("/companies")
        assert response.status_code == 200
        assert b"Alpha" in response.data
        assert b"Beta" in response.data

    def test_toggle_company(self, app, tmp_path):
        from quarry.store.db import Database
        db = Database(tmp_path / "test.db")
        cid = db.insert_company(Company(name="Gamma", ats_type="greenhouse", ats_slug="gamma"))
        assert db.get_company(cid).active is True
        client = app.test_client()
        response = client.post(f"/companies/{cid}/toggle")
        assert response.status_code == 302
        assert db.get_company(cid).active is False
        client.post(f"/companies/{cid}/toggle")
        assert db.get_company(cid).active is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui.py::TestCompaniesRoute -v`
Expected: FAIL

- [ ] **Step 3: Add companies routes to `quarry/ui/routes.py`**

Add the routes:

```python
@bp.route("/companies")
def companies():
    db = get_db()
    active = db.get_all_companies(active_only=True)
    inactive = db.get_all_companies(active_only=False)
    inactive = [c for c in inactive if not c.active]
    return render_template("companies.html", active=active, inactive=inactive)


@bp.route("/companies/<int:company_id>/toggle", methods=["POST"])
def toggle_company(company_id):
    db = get_db()
    company = db.get_company(company_id)
    if company is None:
        return "Company not found", 404
    company.active = not company.active
    db.update_company(company)
    return redirect(url_for("ui.companies"))
```

- [ ] **Step 4: Create `quarry/ui/templates/companies.html`**

```html
{% extends "base.html" %}
{% block title %}Companies — Quarry{% endblock %}
{% block content %}
<h1>Company Watchlist</h1>

<h2>Active ({{ active|length }})</h2>
{% if active %}
<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>ATS</th>
            <th>Domain</th>
            <th>Careers URL</th>
            <th>Action</th>
        </tr>
    </thead>
    <tbody>
        {% for company in active %}
        <tr>
            <td>{{ company.name }}</td>
            <td>{{ company.ats_type }}</td>
            <td>{{ company.domain or "—" }}</td>
            <td>{% if company.careers_url %}<a href="{{ company.careers_url }}">{{ company.careers_url }}</a>{% else %}—{% endif %}</td>
            <td>
                <form method="POST" action="{{ url_for('ui.toggle_company', company_id=company.id) }}" class="inline">
                    <button type="submit" class="small btn-negative">Deactivate</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>No active companies.</p>
{% endif %}

<h2>Inactive ({{ inactive|length }})</h2>
{% if inactive %}
<table>
    <thead>
        <tr>
            <th>Name</th>
            <th>ATS</th>
            <th>Domain</th>
            <th>Action</th>
        </tr>
    </thead>
    <tbody>
        {% for company in inactive %}
        <tr>
            <td>{{ company.name }}</td>
            <td>{{ company.ats_type }}</td>
            <td>{{ company.domain or "—" }}</td>
            <td>
                <form method="POST" action="{{ url_for('ui.toggle_company', company_id=company.id) }}" class="inline">
                    <button type="submit" class="small btn-applied">Reactivate</button>
                </form>
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>No inactive companies.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui.py::TestCompaniesRoute -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quarry/ui/routes.py quarry/ui/templates/companies.html tests/test_ui.py
git commit -m "feat(ui): companies watchlist route with activate/deactivate toggle"
```

---

## Task 6: Agent log route (GET /log)

Read-only view of recent agent actions.

**Files:**
- Modify: `quarry/ui/routes.py`
- Create: `quarry/ui/templates/log.html`
- Test: `tests/test_ui.py` (add log route tests)

- [ ] **Step 1: Write tests for log route**

Add to `tests/test_ui.py`:

```python
class TestLogRoute:
    def test_log_page_renders(self, app, tmp_path):
        from quarry.store.db import Database
        from quarry.models import AgentAction
        db = Database(tmp_path / "test.db")
        db.insert_agent_action(AgentAction(
            run_id="r1", tool_name="add_company",
            tool_args='{"name": "Foo"}', tool_result="Added"
        ))
        client = app.test_client()
        response = client.get("/log")
        assert response.status_code == 200
        assert b"add_company" in response.data

    def test_log_empty(self, app):
        client = app.test_client()
        response = client.get("/log")
        assert response.status_code == 200
        assert b"No agent" in response.data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ui.py::TestLogRoute -v`
Expected: FAIL

- [ ] **Step 3: Add log route to `quarry/ui/routes.py`**

```python
@bp.route("/log")
def log():
    db = get_db()
    actions = db.get_agent_actions(limit=100)
    return render_template("log.html", actions=actions)
```

- [ ] **Step 4: Create `quarry/ui/templates/log.html`**

```html
{% extends "base.html" %}
{% block title %}Agent Log — Quarry{% endblock %}
{% block content %}
<h1>Agent Log</h1>

{% if actions %}
<table>
    <thead>
        <tr>
            <th>Time</th>
            <th>Run ID</th>
            <th>Tool</th>
            <th>Args</th>
            <th>Result</th>
            <th>Rationale</th>
        </tr>
    </thead>
    <tbody>
        {% for action in actions %}
        <tr>
            <td>{{ action.created_at or "—" }}</td>
            <td>{{ action.run_id or "—" }}</td>
            <td>{{ action.tool_name }}</td>
            <td><details>{% if action.tool_args %}<summary>Show</summary><pre>{{ action.tool_args }}</pre>{% else %}—{% endif %}</details></td>
            <td><details>{% if action.tool_result %}<summary>Show</summary><pre>{{ action.tool_result }}</pre>{% else %}—{% endif %}</details></td>
            <td>{{ action.rationale or "—" }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% else %}
<p>No agent actions recorded yet.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_ui.py::TestLogRoute -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quarry/ui/routes.py quarry/ui/templates/log.html tests/test_ui.py
git commit -m "feat(ui): agent log read-only route"
```

---

## Task 7: CLI entrypoint and config update

Add `python -m quarry.ui` entrypoint and add UI config settings.

**Files:**
- Create: `quarry/ui/__main__.py`
- Modify: `quarry/config.py` (add UI host/port settings)
- Modify: `quarry/config.yaml.example` (add UI config section)
- Test: `tests/test_ui.py` (add integration smoke test)

- [ ] **Step 1: Write test for CLI entrypoint**

Add to `tests/test_ui.py`:

```python
class TestCLIEntrypoint:
    def test_app_runs(self, tmp_path):
        from quarry.ui.app import create_app
        db_path = str(tmp_path / "test.db")
        from quarry.store.db import init_db
        init_db(db_path)
        app = create_app(db_path=db_path)
        client = app.test_client()
        response = client.get("/postings")
        assert response.status_code == 200
```

- [ ] **Step 2: Add UI config to `quarry/config.py`**

Add to the `Settings` class (after `filters` field, around line 140):

```python
    # UI
    ui_host: str = "127.0.0.1"
    ui_port: int = 5000
    ui_debug: bool = False
```

- [ ] **Step 3: Create `quarry/ui/__main__.py`**

```python
"""Quarry Labeling UI.

Usage:
    python -m quarry.ui
    python -m quarry.ui --port 8080
"""

import click

from quarry.config import settings
from quarry.store.db import Database


@click.command()
@click.option("--host", default=None, help="Host to bind to (default: from config)")
@click.option("--port", default=None, type=int, help="Port to bind to (default: from config)")
@click.option("--debug", is_flag=True, default=False, help="Enable debug mode")
def main(host: str | None, port: int | None, debug: bool):
    """Run the Quarry labeling UI."""
    from quarry.ui.app import create_app

    app = create_app()
    app.run(
        host=host or settings.ui_host,
        port=port or settings.ui_port,
        debug=debug or settings.ui_debug,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Update `quarry/config.yaml.example`**

Add a UI section at the bottom:

```yaml
# === UI ===
# ui_host: "127.0.0.1"
# ui_port: 5000
# ui_debug: false
```

(Commented out so defaults are used unless overridden.)

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/test_ui.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Run type check**

Run: `PYTHONPATH=/home/kurtt/job-search pyright quarry/ui/`
Expected: No errors.

- [ ] **Step 7: Run lint**

Run: `ruff check quarry/ui/`
Expected: No errors.

- [ ] **Step 8: Run full test suite**

Run: `python -m pytest tests/`
Expected: All 316+ tests PASS.

- [ ] **Step 9: Commit**

```bash
git add quarry/ui/__main__.py quarry/config.py quarry/config.yaml.example tests/test_ui.py
git commit -m "feat(ui): add CLI entrypoint and UI config settings"
```

---

## Verification

After all tasks are complete, verify the full system works:

```bash
# Initialize DB and seed data
python -m quarry.store init
python -m quarry.agent.tools seed

# Run the UI
python -m quarry.ui

# In a browser, verify:
# - http://localhost:5000/ redirects to /postings
# - http://localhost:5000/postings shows postings with status tabs
# - Clicking "Applied" / "Pass" / "Archive" buttons updates status
# - http://localhost:5000/companies shows watchlist with toggles
# - http://localhost:5000/log shows agent actions (read-only)

# Run all tests
python -m pytest tests/
ruff check .
PYTHONPATH=/home/kurtt/job-search pyright quarry/
```

## Post-Implementation: Update STATUS.md

After completing all tasks:
- Mark M8 as **DONE** in STATUS.md
- Add `quarry/ui/` to Key Files section
- Update test count (316 + new UI tests)
- Update verification section with `python -m quarry.ui` command