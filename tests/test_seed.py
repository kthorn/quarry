from pathlib import Path

import yaml

from quarry.agent.tools import seed
from quarry.models import Company
from quarry.store.db import init_db


def _write_seed_file(tmp_path: Path, companies: list[dict]) -> Path:
    seed_file = tmp_path / "seed_data.yaml"
    with open(seed_file, "w") as f:
        yaml.dump(companies, f)
    return seed_file


def test_seed_inserts_companies(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    seed_file = _write_seed_file(
        tmp_path,
        [
            {
                "name": "TestCorp",
                "domain": "testcorp.com",
                "ats_type": "greenhouse",
                "ats_slug": "testcorp",
            },
            {
                "name": "AICo",
                "domain": "aico.com",
                "ats_type": "lever",
                "ats_slug": "aico",
            },
        ],
    )

    inserted, skipped = seed(db=db, seed_file=str(seed_file))

    assert inserted == 2
    assert skipped == 0

    companies = db.get_all_companies(active_only=False)
    names = {c.name for c in companies}
    assert "TestCorp" in names
    assert "AICo" in names


def test_seed_skips_duplicates(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    seed_file = _write_seed_file(
        tmp_path,
        [
            {"name": "TestCorp", "domain": "testcorp.com"},
        ],
    )

    db.insert_company(Company(name="TestCorp", domain="testcorp.com"))

    inserted, skipped = seed(db=db, seed_file=str(seed_file))

    assert inserted == 0
    assert skipped == 1


def test_seed_mixed_insert_and_skip(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    seed_file = _write_seed_file(
        tmp_path,
        [
            {"name": "ExistingCo", "domain": "existing.com"},
            {"name": "NewCo", "domain": "newco.com"},
        ],
    )

    db.insert_company(Company(name="ExistingCo", domain="existing.com"))

    inserted, skipped = seed(db=db, seed_file=str(seed_file))

    assert inserted == 1
    assert skipped == 1

    companies = db.get_all_companies(active_only=False)
    names = {c.name for c in companies}
    assert "NewCo" in names


def test_seed_sets_added_by(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    seed_file = _write_seed_file(
        tmp_path,
        [
            {"name": "TestCorp", "domain": "testcorp.com"},
        ],
    )

    seed(db=db, seed_file=str(seed_file))

    companies = db.get_all_companies(active_only=False)
    assert companies[0].added_by == "seed"


def test_seed_preserves_ats_fields(tmp_path):
    db_path = tmp_path / "test.db"
    db = init_db(db_path)
    seed_file = _write_seed_file(
        tmp_path,
        [
            {
                "name": "TestCorp",
                "domain": "testcorp.com",
                "ats_type": "greenhouse",
                "ats_slug": "testcorp",
                "crawl_priority": 8,
                "added_reason": "Leading AI lab",
            },
        ],
    )

    seed(db=db, seed_file=str(seed_file))

    companies = db.get_all_companies(active_only=False)
    c = companies[0]
    assert c.ats_type == "greenhouse"
    assert c.ats_slug == "testcorp"
    assert c.crawl_priority == 8
    assert c.added_reason == "Leading AI lab"
