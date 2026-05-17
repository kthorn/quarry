"""Integration tests for settings UI routes (Task 7).

Tests the 13 settings-related POST routes and the GET /settings page
using the Flask test client pattern from tests/test_ui.py.
"""

import pytest

from quarry.models import UserSearchQuery
from quarry.settings_service import UserSettingsService
from quarry.store.db import Database, init_db
from quarry.ui.app import create_app

USER_ID = 1


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


def _ss(db):
    """Helper to build a UserSettingsService for the default user."""
    return UserSettingsService(db, user_id=USER_ID)


class TestSettingsGet:
    """GET /settings — page rendering and section navigation."""

    def test_settings_page_renders(self, client):
        """GET /settings returns 200 and contains 'Settings' text."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert b"Settings" in response.data or b"settings" in response.data.lower()

    def test_settings_page_with_section(self, client):
        """GET /settings?section=blocklist returns 200."""
        response = client.get("/settings?section=blocklist")
        assert response.status_code == 200


class TestSettingsQueries:
    """POST /settings/queries/add and /settings/queries/<id>/retire."""

    def test_settings_queries_add(self, client, tmp_path):
        """POST /settings/queries/add adds a search query visible via DB."""
        response = client.post(
            "/settings/queries/add",
            data={"query_text": "software engineer", "reason": "test"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Added search query" in response.data

        db = Database(tmp_path / "test.db")
        queries = db.get_all_search_queries(user_id=USER_ID)
        texts = [q.query_text for q in queries]
        assert "software engineer" in texts

    def test_settings_queries_add_duplicate(self, client, tmp_path):
        """Adding the same query twice flashes error on second attempt."""
        client.post(
            "/settings/queries/add",
            data={"query_text": "data scientist"},
            follow_redirects=True,
        )

        response = client.post(
            "/settings/queries/add",
            data={"query_text": "data scientist"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert (
            b"already exists" in response.data or b"duplicate" in response.data.lower()
        )

    def test_settings_queries_retire(self, client, tmp_path):
        """POST /settings/queries/<id>/retire deactivates the query."""
        db = Database(tmp_path / "test.db")
        qid = db.insert_search_query(
            UserSearchQuery(user_id=USER_ID, query_text="machine learning"),
            user_id=USER_ID,
        )

        response = client.post(
            f"/settings/queries/{qid}/retire",
            data={"reason": "no longer needed"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Query retired" in response.data

        queries = db.get_all_search_queries(user_id=USER_ID)
        retired = [q for q in queries if q.id == qid]
        assert len(retired) == 1
        assert retired[0].active is False
        assert retired[0].retired_reason == "no longer needed"


class TestSettingsRoleDescription:
    """POST /settings/role-description."""

    def test_settings_role_description(self, client, tmp_path):
        """POST /settings/role-description saves description text."""
        response = client.post(
            "/settings/role-description",
            data={
                "description": "Experienced data engineer building scalable pipelines."
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"saved" in response.data.lower()

        db = Database(tmp_path / "test.db")
        saved = _ss(db).get_ideal_role_description()
        assert "data engineer" in saved.lower()

    def test_settings_role_description_empty(self, client, tmp_path):
        """Posting an empty description saves it (clears previous)."""
        db = Database(tmp_path / "test.db")
        _ss(db).set_ideal_role_description("Some previous description")

        response = client.post(
            "/settings/role-description",
            data={"description": ""},
            follow_redirects=True,
        )
        assert response.status_code == 200

        saved = _ss(db).get_ideal_role_description()
        assert saved == ""


class TestSettingsSimilarity:
    """POST /settings/similarity."""

    def test_settings_similarity(self, client, tmp_path):
        """POST /settings/similarity saves the threshold value."""
        response = client.post(
            "/settings/similarity",
            data={"threshold": "0.75"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        # The route does not flash when using the current code path,
        # but we can check the redirect was followed.

        db = Database(tmp_path / "test.db")
        saved = _ss(db).get_similarity_threshold()
        assert saved == 0.75

    def test_settings_similarity_out_of_range(self, client, tmp_path):
        """Threshold of 1.5 is clamped to 1.0."""
        response = client.post(
            "/settings/similarity",
            data={"threshold": "1.5"},
            follow_redirects=True,
        )
        assert response.status_code == 200

        db = Database(tmp_path / "test.db")
        saved = _ss(db).get_similarity_threshold()
        assert saved == 1.0

    def test_settings_similarity_below_zero(self, client, tmp_path):
        """Threshold of -0.5 is clamped to 0.0."""
        response = client.post(
            "/settings/similarity",
            data={"threshold": "-0.5"},
            follow_redirects=True,
        )
        assert response.status_code == 200

        db = Database(tmp_path / "test.db")
        saved = _ss(db).get_similarity_threshold()
        assert saved == 0.0

    def test_settings_similarity_invalid(self, client, tmp_path):
        """Non-numeric threshold flashes an error."""
        response = client.post(
            "/settings/similarity",
            data={"threshold": "not-a-number"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Invalid" in response.data

        # Existing threshold should remain unchanged
        db = Database(tmp_path / "test.db")
        saved = _ss(db).get_similarity_threshold()
        # No custom value set, so falls back to config default
        from quarry.config import settings as cfg

        assert saved == cfg.similarity_threshold


class TestSettingsBlocklist:
    """POST /settings/blocklist."""

    def test_settings_blocklist(self, client, tmp_path):
        """POST /settings/blocklist saves keywords and passlist."""
        response = client.post(
            "/settings/blocklist",
            data={
                "keywords": "toxic\nnoise",
                "passlist": "engineering",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"blocklist saved" in response.data.lower()

        db = Database(tmp_path / "test.db")
        bl = _ss(db).get_keyword_blocklist()
        assert bl is not None
        assert "toxic" in bl.keywords
        assert "noise" in bl.keywords
        assert "engineering" in bl.passlist

    def test_settings_empty_blocklist(self, client, tmp_path):
        """An empty blocklist submission saves an empty config."""
        response = client.post(
            "/settings/blocklist",
            data={"keywords": "", "passlist": ""},
            follow_redirects=True,
        )
        assert response.status_code == 200

        db = Database(tmp_path / "test.db")
        bl = _ss(db).get_keyword_blocklist()
        assert bl is not None
        assert bl.keywords == []
        assert bl.passlist == []


class TestSettingsTitleKeywords:
    """POST /settings/title-keywords."""

    def test_settings_title_keywords(self, client, tmp_path):
        """POST /settings/title-keywords saves keywords."""
        response = client.post(
            "/settings/title-keywords",
            data={"keywords": "engineer\narchitect\ndeveloper"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"keywords saved" in response.data.lower()

        db = Database(tmp_path / "test.db")
        tk = _ss(db).get_title_keywords()
        assert tk is not None
        assert "engineer" in tk.keywords
        assert "architect" in tk.keywords
        assert "developer" in tk.keywords

    def test_settings_empty_title_keywords(self, client, tmp_path):
        """An empty title keywords submission saves an empty config."""
        response = client.post(
            "/settings/title-keywords",
            data={"keywords": ""},
            follow_redirects=True,
        )
        assert response.status_code == 200

        db = Database(tmp_path / "test.db")
        tk = _ss(db).get_title_keywords()
        assert tk is not None
        assert tk.keywords == []


class TestSettingsCompanyFilter:
    """POST /settings/company-filter."""

    def test_settings_company_filter(self, client, tmp_path):
        """POST /settings/company-filter saves allow/deny lists."""
        response = client.post(
            "/settings/company-filter",
            data={
                "allow": "Google\nMeta",
                "deny": "Enron\nTheranos",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"company filter saved" in response.data.lower()

        db = Database(tmp_path / "test.db")
        cf = _ss(db).get_company_filter()
        assert cf is not None
        assert "Google" in cf.allow
        assert "Meta" in cf.allow
        assert "Enron" in cf.deny
        assert "Theranos" in cf.deny

    def test_settings_empty_company_filter(self, client, tmp_path):
        """An empty company filter saves with empty allow/deny."""
        response = client.post(
            "/settings/company-filter",
            data={"allow": "", "deny": ""},
            follow_redirects=True,
        )
        assert response.status_code == 200

        db = Database(tmp_path / "test.db")
        cf = _ss(db).get_company_filter()
        assert cf is not None
        assert cf.allow == []
        assert cf.deny == []


class TestSettingsLocation:
    """POST /settings/location."""

    def test_settings_location(self, client, tmp_path):
        """POST /settings/location saves location config with city and remote flag.

        Verifies the round-trip: getter calls normalize_config internally.
        """
        response = client.post(
            "/settings/location",
            data={
                "target_location": "San Francisco, CA\nNew York, NY",
                "accept_remote": "on",
                "nearby_radius": "50",
                "accept_states": "CA\nNY",
                "accept_regions": "US-West\nUS-East",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"location filter saved" in response.data.lower()

        db = Database(tmp_path / "test.db")
        lf = _ss(db).get_location_filter()
        assert lf is not None
        assert "San Francisco, CA" in lf.target_location
        assert "New York, NY" in lf.target_location
        assert lf.accept_remote is True
        assert lf.nearby_radius == 50
        assert "CA" in lf.accept_states
        assert "NY" in lf.accept_states
        assert "US-West" in lf.accept_regions
        assert "US-East" in lf.accept_regions

    def test_settings_location_without_remote(self, client, tmp_path):
        """When accept_remote is unchecked, it's set to False."""
        response = client.post(
            "/settings/location",
            data={
                "target_location": "Chicago, IL",
                "nearby_radius": "",
                "accept_states": "",
                "accept_regions": "",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        db = Database(tmp_path / "test.db")
        lf = _ss(db).get_location_filter()
        assert lf is not None
        assert lf.accept_remote is False
        assert "Chicago, IL" in lf.target_location

    def test_settings_location_empty(self, client, tmp_path):
        """Empty location submission saves a minimal config."""
        response = client.post(
            "/settings/location",
            data={
                "target_location": "",
                "accept_remote": "",
                "nearby_radius": "",
                "accept_states": "",
                "accept_regions": "",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

        db = Database(tmp_path / "test.db")
        lf = _ss(db).get_location_filter()
        assert lf is not None
        assert lf.target_location == []
        assert lf.accept_remote is False
        assert lf.nearby_radius is None


class TestSettingsJobSpy:
    """POST /settings/jobspy."""

    def test_settings_jobspy(self, client, tmp_path):
        """POST /settings/jobspy saves selected sites and numbers."""
        response = client.post(
            "/settings/jobspy",
            data={
                "sites": ["indeed", "linkedin"],
                "results_wanted": "30",
                "hours_old": "72",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"settings saved" in response.data.lower()

        db = Database(tmp_path / "test.db")
        cfg = _ss(db).get_jobspy_config()
        assert "indeed" in cfg["sites"]
        assert "linkedin" in cfg["sites"]
        assert cfg["results_wanted"] == 30
        assert cfg["hours_old"] == 72

    def test_settings_jobspy_invalid_results_wanted(self, client, tmp_path):
        """Invalid results_wanted value flashes an error."""
        response = client.post(
            "/settings/jobspy",
            data={
                "sites": ["indeed"],
                "results_wanted": "not-a-number",
                "hours_old": "168",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Invalid" in response.data

    def test_settings_jobspy_validates_sites(self, client, tmp_path):
        """Only valid site names are saved; unknown sites are filtered out."""
        response = client.post(
            "/settings/jobspy",
            data={
                "sites": ["indeed", "nonexistent-site"],
                "results_wanted": "20",
                "hours_old": "168",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"settings saved" in response.data.lower()

        db = Database(tmp_path / "test.db")
        cfg = _ss(db).get_jobspy_config()
        assert "indeed" in cfg["sites"]
        assert "nonexistent-site" not in cfg["sites"]


class TestSettingsInitiallyNone:
    """Verify that UserSettingsService returns None for unconfigured settings."""

    def test_blocklist_initially_none(self, tmp_path):
        """get_keyword_blocklist() returns None when no DB override exists."""
        db = init_db(tmp_path / "test.db")
        result = _ss(db).get_keyword_blocklist()
        assert result is None

    def test_title_keywords_initially_none(self, tmp_path):
        """get_title_keywords() returns None when no DB override exists."""
        db = init_db(tmp_path / "test.db")
        result = _ss(db).get_title_keywords()
        assert result is None

    def test_company_filter_initially_none(self, tmp_path):
        """get_company_filter() returns None when no DB override exists."""
        db = init_db(tmp_path / "test.db")
        result = _ss(db).get_company_filter()
        assert result is None

    def test_location_filter_initially_none(self, tmp_path):
        """get_location_filter() returns None when no DB override exists."""
        db = init_db(tmp_path / "test.db")
        result = _ss(db).get_location_filter()
        assert result is None
