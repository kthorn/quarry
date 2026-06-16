"""Tests for Database CRUD methods (DB-level) and Flask routes (skipped until Phase 4).

DB-level tests have been updated for the Phase 3 multi-user schema:
- JobPosting no longer has status/similarity_score fields
- Label → UserLabel
- Database methods now require user_id (defaults to 1)
- Status/similarity score accessed via dedicated per-user tables
"""

import pytest

from quarry.models import AgentAction, Company, JobPosting
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
        results = db.get_postings_with_scores(interest="interested")
        assert results == []

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

    def test_interest_positive(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="AcmeCorp")
        cid = db.insert_company(company)
        pid = db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Engineer",
                title_hash="int_pos",
                url="https://example.com/int_pos",
            )
        )
        db.set_interest(pid, True)
        results = db.get_postings_with_scores()
        assert results[0]["interest"] is True

    def test_interest_negative(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="AcmeCorp")
        cid = db.insert_company(company)
        pid = db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Engineer",
                title_hash="int_neg",
                url="https://example.com/int_neg",
            )
        )
        db.set_interest(pid, False)
        results = db.get_postings_with_scores()
        assert results[0]["interest"] is False

    def test_interest_replaces_previous(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="AcmeCorp")
        cid = db.insert_company(company)
        pid = db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Engineer",
                title_hash="int_latest",
                url="https://example.com/int_latest",
            )
        )
        db.set_interest(pid, False)
        db.set_interest(pid, True)
        results = db.get_postings_with_scores()
        assert results[0]["interest"] is True

    def test_interest_with_applied(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="AcmeCorp")
        cid = db.insert_company(company)
        pid = db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Engineer",
                title_hash="int_applied",
                url="https://example.com/int_applied",
            )
        )
        db.set_applied(pid, True)
        results = db.get_postings_with_scores()
        assert results[0]["interest"] is None
        assert results[0]["applied"] is True


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

    def test_postings_empty(self, app):
        client = app.test_client()
        response = client.get("/postings")
        assert response.status_code == 200
        assert b"No postings" in response.data


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


class TestRetrainRoute:
    def test_retrain_redirects_to_postings(self, app):
        """POST /retrain should redirect back to /postings."""
        client = app.test_client()
        response = client.post("/retrain")
        assert response.status_code == 302
        assert "/postings" in response.headers["Location"]


class TestScanRoute:
    def test_scan_redirects_to_postings(self, app):
        """POST /scan should redirect back to /postings."""
        client = app.test_client()
        response = client.post("/scan")
        assert response.status_code == 302
        assert "/postings" in response.headers["Location"]

    def test_scan_preserves_interest_and_q(self, app):
        """POST /scan should preserve return_interest and q in redirect."""
        client = app.test_client()
        response = client.post(
            "/scan", data={"return_interest": "interested", "q": "engineer"}
        )
        assert response.status_code == 302
        location = response.headers["Location"]
        assert "interest=interested" in location
        assert "q=engineer" in location

    def test_scan_flash_on_error(self, app):
        """POST /scan should flash error when run_once fails."""
        from unittest import mock

        with mock.patch("quarry.agent.scheduler.run_once") as mock_run:
            mock_run.side_effect = Exception("API timeout")
            client = app.test_client()
            response = client.post("/scan", follow_redirects=True)
            assert response.status_code == 200
            assert b"Scan failed" in response.data
            assert b"API timeout" in response.data


# ── Template Tests (Task 3: postings.html badges, form actions, scan button) ─


@pytest.fixture
def app_with_labels(app, tmp_path):
    """Fixture with a posting that has interest labels."""
    db = Database(tmp_path / "test.db")
    company = Company(name="LabelCo", ats_type="greenhouse", ats_slug="labelco")
    cid = db.insert_company(company)
    posting = JobPosting(
        company_id=cid,
        title="ML Engineer",
        title_hash="hash_labeltest",
        url="https://labelco.com/job/1",
        description="Build ML models",
        location="Remote, US",
        work_model="remote",
        source_type="greenhouse",
    )
    pid = db.insert_posting(posting)
    db.set_interest(pid, True)
    return app


class TestPostingsTemplateBadges:
    def test_interest_positive_badge_renders(self, app_with_labels):
        """When a posting has a positive interest signal, 'Interested' badge shows."""
        client = app_with_labels.test_client()
        response = client.get("/postings")
        assert response.status_code == 200
        html = response.data.decode()
        assert "badge-positive" in html
        assert "Interested" in html

    def test_interest_negative_badge_renders(self, app, tmp_path):
        """When a posting has a negative interest signal, 'Not Interested' badge shows."""
        db = Database(tmp_path / "test.db")
        company = Company(name="NegativeCo")
        cid = db.insert_company(company)
        posting = JobPosting(
            company_id=cid,
            title="Junior Dev",
            title_hash="hash_negbadge",
            url="https://negco.com/job/1",
            description="Entry level",
        )
        pid = db.insert_posting(posting)
        db.set_interest(pid, False)
        client = app.test_client()
        response = client.get("/postings")
        assert response.status_code == 200
        html = response.data.decode()
        assert "badge-negative" in html
        assert "Not Interested" in html

    def test_no_interest_badge_when_no_interest(self, app_with_postings):
        """When no interest exists, neither badge should render."""
        with app_with_postings.test_client() as client:
            resp = client.get("/postings")
            html = resp.data.decode()
            assert resp.status_code == 200
            assert "badge-positive" not in html
            assert "badge-negative" not in html


class TestLabelFormParams:
    def test_label_forms_have_interest_inputs(self, app_with_postings):
        """Interest buttons use hidden 'interest' field."""
        with app_with_postings.test_client() as client:
            resp = client.get("/postings")
            html = resp.data.decode()
            assert 'name="interest" value="positive"' in html
            assert 'name="interest" value="negative"' in html

    def test_label_forms_have_applied_input(self, app_with_postings):
        """Applied button uses hidden 'applied' field."""
        with app_with_postings.test_client() as client:
            resp = client.get("/postings")
            html = resp.data.decode()
            assert 'name="applied" value="true"' in html


class TestPostingsTemplateScanButton:
    def test_scan_button_in_toolbar(self, app):
        """The 'Run Scan' button should appear in the toolbar."""
        client = app.test_client()
        response = client.get("/postings")
        assert response.status_code == 200
        html = response.data.decode()
        assert "Run Scan" in html
        assert "/scan" in html
        assert "scan-form" in html


class TestCompanyDescriptionRoutes:
    """Task 5: Company description update and regenerate routes."""

    def test_update_description(self, client, tmp_path):
        """POST /companies/<id>/description updates the description."""
        db = Database(tmp_path / "test.db")
        company = Company(name="TestCo", domain="testco.com")
        company_id = db.insert_company(company)

        response = client.post(
            f"/companies/{company_id}/description",
            data={"description": "TestCo builds tests."},
            follow_redirects=True,
        )
        assert response.status_code == 200

        updated = db.get_company(company_id)
        assert updated is not None
        assert updated.description == "TestCo builds tests."
        assert updated.description_source == "manual"

    def test_regenerate_description(self, client, tmp_path, monkeypatch):
        """POST /companies/<id>/regenerate triggers description generation."""
        db = Database(tmp_path / "test.db")
        company = Company(name="TestCo", domain="testco.com")
        company_id = db.insert_company(company)

        def mock_generate(company):
            return "Generated description.", "wikipedia"

        monkeypatch.setattr(
            "quarry.resolve.description.generate_company_description",
            mock_generate,
        )

        response = client.post(
            f"/companies/{company_id}/regenerate",
            follow_redirects=True,
        )
        assert response.status_code == 200

        updated = db.get_company(company_id)
        assert updated is not None
        assert updated.description == "Generated description."
        assert updated.description_source == "wikipedia"

    def test_regenerate_description_handles_error(self, client, tmp_path, monkeypatch):
        """POST /companies/<id>/regenerate sets description to pending on error."""
        db = Database(tmp_path / "test.db")
        company = Company(name="TestCo", domain="testco.com")
        company_id = db.insert_company(company)

        def mock_generate(company):
            raise RuntimeError("LLM unavailable")

        monkeypatch.setattr(
            "quarry.resolve.description.generate_company_description",
            mock_generate,
        )

        response = client.post(
            f"/companies/{company_id}/regenerate",
            follow_redirects=True,
        )
        assert response.status_code == 200

        updated = db.get_company(company_id)
        assert updated is not None
        assert updated.description is None
        assert updated.description_source == "pending"

    def test_update_description_404_on_missing_company(self, client):
        """POST /companies/<id>/description returns 404 for missing company."""
        response = client.post(
            "/companies/99999/description",
            data={"description": "Nope"},
        )
        assert response.status_code == 404


class TestActivateCompanyDeferredDescription:
    """Task 5: activate_company() defers description generation in background."""

    def test_activate_sets_pending_on_no_description(self, client, tmp_path):
        """Activating a company without description sets source=pending."""
        db = Database(tmp_path / "test.db")
        from quarry.models import UserWatchlistItem

        # Create a discovered (inactive) company without description
        company = Company(
            name="NewCo",
            domain="newco.com",
            resolve_status="resolved",
            description=None,
            description_source=None,
        )
        company_id = db.insert_company(company)
        # Make it inactive as if discovered via search
        db.upsert_watchlist_item(
            UserWatchlistItem(
                user_id=1, company_id=company_id, active=False, added_reason="search"
            )
        )

        response = client.post(
            f"/companies/{company_id}/activate",
            follow_redirects=True,
        )
        assert response.status_code == 200

        updated = db.get_company(company_id)
        assert updated is not None
        # Should be set to pending (deferred generation started in background)
        assert updated.description_source == "pending"


class TestCompaniesDiscovered:
    def test_companies_page_shows_discovered(self, app, tmp_path):
        db = Database(tmp_path / "test.db")
        from quarry.models import Company, UserWatchlistItem

        # Create a discovered company
        company = Company(name="SearchCo")
        company.id = db.insert_company(company)
        db.upsert_watchlist_item(
            UserWatchlistItem(
                user_id=1, company_id=company.id, active=False, added_reason="search"
            )
        )

        # Also create a seed company
        seed = Company(name="SeedCo")
        seed.id = db.insert_company(seed)
        db.upsert_watchlist_item(
            UserWatchlistItem(
                user_id=1, company_id=seed.id, active=True, added_reason="seed"
            )
        )

        client = app.test_client()
        resp = client.get("/companies")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Discovered via Search" in html
        assert "SearchCo" in html
        assert "SeedCo" in html


class TestCompaniesPageCards:
    def test_companies_page_renders_cards(self, app, tmp_path):
        """Companies page renders cards instead of tables."""
        db = Database(tmp_path / "test.db")
        company = Company(name="TestCo", domain="testco.com", ats_type="greenhouse")
        company_id = db.insert_company(company)
        db.update_company_description(company_id, "TestCo builds things.", "manual")

        client = app.test_client()
        response = client.get("/companies")
        assert response.status_code == 200
        html = response.data.decode()

        # Should use card class, not table
        assert "company-card" in html
        # Verify card-based layout (old table layout replaced)
        assert '<div class="card company-card">' in html

        # Should show description
        assert "TestCo builds things." in html

        # Should show edit/regenerate buttons
        assert "Edit" in html
        assert "Regenerate" in html

        # Em dash should not appear for missing fields
        assert "\u2014" not in html
