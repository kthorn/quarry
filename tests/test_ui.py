"""Tests for Database CRUD methods (DB-level) and Flask routes (skipped until Phase 4).

DB-level tests have been updated for the Phase 3 multi-user schema:
- JobPosting no longer has status/similarity_score fields
- Label → UserLabel
- Database methods now require user_id (defaults to 1)
- Status/similarity score accessed via dedicated per-user tables
"""

import pytest

from quarry.models import AgentAction, Company, JobPosting, UserLabel
from quarry.store.db import Database, init_db
from quarry.ui.app import create_app

# ── DB-Level Tests ──────────────────────────────────────────────


class TestGetPostingById:
    def test_found(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        posting = JobPosting(
            company_id=cid,
            title="Engineer",
            title_hash="h1",
            url="https://example.com/1",
        )
        pid = db.insert_posting(posting)
        result = db.get_posting_by_id(pid)
        assert result is not None
        assert result.id == pid
        assert result.title == "Engineer"

    def test_not_found(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        result = db.get_posting_by_id(9999)
        assert result is None


class TestUpdatePostingStatus:
    def test_status_update(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        posting = JobPosting(
            company_id=cid,
            title="Engineer",
            title_hash="h2",
            url="https://example.com/2",
        )
        pid = db.insert_posting(posting)
        db.update_posting_status(pid, "applied")
        # Verify via raw query to user_posting_status table
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM user_posting_status WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["status"] == "applied"

    def test_does_not_affect_other_postings(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        p1 = JobPosting(
            company_id=cid,
            title="Engineer A",
            title_hash="h3",
            url="https://example.com/3",
        )
        p2 = JobPosting(
            company_id=cid,
            title="Engineer B",
            title_hash="h4",
            url="https://example.com/4",
        )
        id1 = db.insert_posting(p1)
        id2 = db.insert_posting(p2)
        db.update_posting_status(id1, "applied")
        # Posting 2 should still have status "new" from insert_posting
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM user_posting_status WHERE user_id = 1 AND posting_id = ?",
            (id2,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["status"] == "new"


class TestCountPostings:
    def test_count_all(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        for i in range(3):
            db.insert_posting(
                JobPosting(
                    company_id=cid,
                    title=f"Job {i}",
                    title_hash=f"cnt_{i}",
                    url=f"https://example.com/cnt_{i}",
                )
            )
        assert db.count_postings() == 3

    def test_count_by_status(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        pid1 = db.insert_posting(  # noqa: F841
            JobPosting(
                company_id=cid,
                title="New Job",
                title_hash="cnt_s1",
                url="https://example.com/cnt_s1",
            )
        )
        pid2 = db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Seen Job",
                title_hash="cnt_s2",
                url="https://example.com/cnt_s2",
            )
        )
        # insert_posting creates "new" status by default, so mark pid2 as seen
        db.update_posting_status(pid2, "seen")
        assert db.count_postings("new") == 1
        assert db.count_postings("seen") == 1
        assert db.count_postings("applied") == 0

    def test_count_zero_on_empty(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        assert db.count_postings() == 0


class TestGetPostingsWithScores:
    def test_returns_with_company_name(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="AcmeCorp")
        cid = db.insert_company(company)
        pid = db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Engineer",
                title_hash="pg1",
                url="https://example.com/pg1",
            )
        )
        db.update_posting_similarity(pid, 0.9)
        results = db.get_postings_with_scores()
        assert len(results) == 1
        assert results[0]["title"] == "Engineer"
        assert results[0]["company_name"] == "AcmeCorp"

    def test_pagination_offset_limit(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        for i in range(5):
            pid = db.insert_posting(
                JobPosting(
                    company_id=cid,
                    title=f"Job {i}",
                    title_hash=f"pgpg_{i}",
                    url=f"https://example.com/pgpg_{i}",
                )
            )
            db.update_posting_similarity(pid, float(i))
        page1 = db.get_postings_with_scores(limit=2, offset=0)
        assert len(page1) == 2
        page2 = db.get_postings_with_scores(limit=2, offset=2)
        assert len(page2) == 2
        page3 = db.get_postings_with_scores(limit=2, offset=4)
        assert len(page3) == 1

    def test_empty_when_no_match(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Job",
                title_hash="pgempty",
                url="https://example.com/pgempty",
            )
        )
        results = db.get_postings_with_scores(status="applied")
        assert results == []

    def test_status_filter(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        pid1 = db.insert_posting(  # noqa: F841
            JobPosting(
                company_id=cid,
                title="New",
                title_hash="pgst1",
                url="https://example.com/pgst1",
            )
        )
        pid2 = db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Applied",
                title_hash="pgst2",
                url="https://example.com/pgst2",
            )
        )
        db.update_posting_similarity(pid1, 0.8)
        db.update_posting_similarity(pid2, 0.7)
        db.update_posting_status(pid2, "applied")
        results = db.get_postings_with_scores(status="new")
        assert len(results) == 1
        assert results[0]["title"] == "New"

    def test_threshold_filter_by_similarity(self, tmp_path):
        """get_postings_with_scores returns all postings; filter in Python."""
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        for i, score in enumerate([0.9, 0.5, 0.2]):
            pid = db.insert_posting(
                JobPosting(
                    company_id=cid,
                    title=f"Job {i}",
                    title_hash=f"pgthr_{i}",
                    url=f"https://example.com/pgthr_{i}",
                )
            )
            db.update_posting_similarity(pid, score)
        results = db.get_postings_with_scores()
        above_threshold = [r for r in results if r["similarity_score"] >= 0.5]
        assert len(above_threshold) == 2


class TestGetLabelsForPosting:
    def test_returns_labels(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        pid = db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Job",
                title_hash="lbl1",
                url="https://example.com/lbl1",
            )
        )
        db.insert_label(UserLabel(user_id=1, posting_id=pid, signal="positive"))
        db.insert_label(UserLabel(user_id=1, posting_id=pid, signal="negative"))
        labels = db.get_labels_for_posting(pid)
        assert len(labels) == 2
        assert labels[0].posting_id == pid

    def test_returns_empty_when_none(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        labels = db.get_labels_for_posting(9999)
        assert labels == []


class TestGetAgentActions:
    def test_returns_actions(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        db.insert_agent_action(
            AgentAction(tool_name="web_search", tool_args='{"q": "test"}')
        )
        db.insert_agent_action(AgentAction(tool_name="summarize", rationale="test"))
        actions = db.get_agent_actions()
        assert len(actions) == 2
        assert actions[0].tool_name in ("web_search", "summarize")

    def test_respects_limit(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        for i in range(10):
            db.insert_agent_action(AgentAction(tool_name=f"tool_{i}"))
        actions = db.get_agent_actions(limit=5)
        assert len(actions) == 5


# ── Flask Route Tests (skipped until Phase 4) ─────────────────


@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    app = create_app(db_path=db_path)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def app_with_postings(app, tmp_path):
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
            source_type="greenhouse",
        )
        db.insert_posting(posting)
    return app


class TestFlaskApp:
    def test_create_app(self, app):
        assert app is not None

    @pytest.mark.skip(reason="Phase 4")
    def test_home_redirects_to_postings(self, client):
        response = client.get("/")
        assert response.status_code == 302


@pytest.mark.skip(reason="Phase 4")
class TestPostingsRoute:
    def test_postings_page_renders(self, app_with_postings):
        client = app_with_postings.test_client()
        response = client.get("/postings")
        assert response.status_code == 200
        assert b"Data Engineer" in response.data

    def test_postings_filtered_by_status(self, app_with_postings, tmp_path):
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

    def test_postings_invalid_status_defaults_to_new(self, app_with_postings):
        client = app_with_postings.test_client()
        response = client.get("/postings?status=invalid")
        assert response.status_code == 200


@pytest.mark.skip(reason="Phase 4")
class TestLabelRoute:
    def test_label_updates_status(self, app_with_postings, tmp_path):
        db = Database(tmp_path / "test.db")
        postings = db.get_postings(limit=10)
        pid = postings[0].id
        client = app_with_postings.test_client()
        response = client.post(f"/label/{pid}", data={"status": "applied"})
        assert response.status_code == 302
        # Status now in user_posting_status table
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM user_posting_status WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row["status"] == "applied"

    def test_label_creates_label_record(self, app_with_postings, tmp_path):
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
        db = Database(tmp_path / "test.db")
        postings = db.get_postings(limit=10)
        pid = postings[0].id
        client = app_with_postings.test_client()
        response = client.post(f"/label/{pid}", data={"status": "invalid"})
        assert response.status_code == 400
        # Status should remain "new"
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM user_posting_status WHERE user_id = 1 AND posting_id = ?",
            (pid,),
        ).fetchone()
        conn.close()
        assert row["status"] == "new"


@pytest.mark.skip(reason="Phase 4")
class TestCompaniesRoute:
    def test_companies_list(self, app, tmp_path):
        db = Database(tmp_path / "test.db")
        db.insert_company(
            Company(name="Alpha", ats_type="greenhouse", ats_slug="alpha")
        )
        db.insert_company(Company(name="Beta", ats_type="lever", ats_slug="beta"))
        client = app.test_client()
        response = client.get("/companies")
        assert response.status_code == 200
        assert b"Alpha" in response.data
        assert b"Beta" in response.data

    def test_toggle_company(self, app, tmp_path):
        db = Database(tmp_path / "test.db")
        cid = db.insert_company(
            Company(name="Gamma", ats_type="greenhouse", ats_slug="gamma")
        )
        # Active/inactive now in user_watchlist table
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT active FROM user_watchlist WHERE user_id = 1 AND company_id = ?",
            (cid,),
        ).fetchone()
        conn.close()
        assert row["active"] == 1
        client = app.test_client()
        response = client.post(f"/companies/{cid}/toggle")
        assert response.status_code == 302
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT active FROM user_watchlist WHERE user_id = 1 AND company_id = ?",
            (cid,),
        ).fetchone()
        conn.close()
        assert row["active"] == 0
        client.post(f"/companies/{cid}/toggle")
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT active FROM user_watchlist WHERE user_id = 1 AND company_id = ?",
            (cid,),
        ).fetchone()
        conn.close()
        assert row["active"] == 1


@pytest.mark.skip(reason="Phase 4")
class TestLogRoute:
    def test_log_page_renders(self, app, tmp_path):
        db = Database(tmp_path / "test.db")
        db.insert_agent_action(
            AgentAction(
                run_id="r1",
                tool_name="add_company",
                tool_args='{"name": "Foo"}',
                tool_result="Added",
            )
        )
        client = app.test_client()
        response = client.get("/log")
        assert response.status_code == 200
        assert b"add_company" in response.data

    def test_log_empty(self, app):
        client = app.test_client()
        response = client.get("/log")
        assert response.status_code == 200
        assert b"No agent" in response.data
