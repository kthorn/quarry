import pytest
import yaml

from quarry.agent.tools import load_seed_data, seed
from quarry.models import Company
from quarry.store.db import init_db


@pytest.fixture
def db(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def seed_file(tmp_path):
    """Create a minimal seed file for testing."""
    data = {
        "companies": [
            {
                "name": "TestCorp",
                "ats_type": "greenhouse",
                "ats_slug": "testcorp",
                "domain": "testcorp.com",
            },
        ],
        "search_queries": [
            {"query_text": "People Analytics Manager", "added_reason": "Direct match"},
        ],
    }
    path = tmp_path / "seed_data.yaml"
    path.write_text(yaml.dump(data))
    return str(path)


@pytest.fixture
def legacy_seed_file(tmp_path):
    """Create a legacy flat-list seed file for testing."""
    data = [
        {
            "name": "TestCorp",
            "ats_type": "greenhouse",
            "ats_slug": "testcorp",
            "domain": "testcorp.com",
        },
    ]
    path = tmp_path / "legacy_seed.yaml"
    path.write_text(yaml.dump(data))
    return str(path)


class TestLoadSeedData:
    def test_load_companies_from_yaml(self, db, seed_file):
        companies, queries = load_seed_data(seed_file)
        assert len(companies) == 1
        assert companies[0].name == "TestCorp"
        assert companies[0].ats_type == "greenhouse"

    def test_load_queries_from_yaml(self, db, seed_file):
        companies, queries = load_seed_data(seed_file)
        assert len(queries) == 1
        assert queries[0].query_text == "People Analytics Manager"

    def test_load_raises_for_missing_file(self, db):
        with pytest.raises(SystemExit):
            load_seed_data("/nonexistent/path.yaml")

    def test_load_legacy_flat_list(self, db, legacy_seed_file):
        companies, queries = load_seed_data(legacy_seed_file)
        assert len(companies) == 1
        assert companies[0].name == "TestCorp"
        assert len(queries) == 0


class TestSeed:
    def test_seed_inserts_into_db(self, db, seed_file):
        seed(db, seed_file)
        companies = db.get_all_companies(active_only=False)
        assert len(companies) == 1
        assert companies[0].name == "TestCorp"

    def test_seed_is_idempotent(self, db, seed_file):
        seed(db, seed_file)
        seed(db, seed_file)
        companies = db.get_all_companies(active_only=False)
        assert len(companies) == 1

    def test_seed_inserts_queries(self, db, seed_file):
        seed(db, seed_file)
        queries = db.get_active_search_queries()
        assert len(queries) == 1

    def test_seed_preserves_ats_fields(self, db, seed_file):
        seed(db, seed_file)
        companies = db.get_all_companies(active_only=False)
        assert companies[0].ats_type == "greenhouse"
        assert companies[0].ats_slug == "testcorp"

    def test_seed_mixed_insert_and_skip(self, db, tmp_path):
        data = {
            "companies": [
                {"name": "ExistingCo", "domain": "existing.com"},
                {"name": "NewCo", "domain": "newco.com"},
            ],
        }
        path = tmp_path / "seed_data.yaml"
        path.write_text(yaml.dump(data))
        db.insert_company(Company(name="ExistingCo", domain="existing.com"))
        inserted, skipped = seed(db, str(path))
        assert inserted == 1
        assert skipped == 1
