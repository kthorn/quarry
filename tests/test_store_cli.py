from unittest.mock import patch

from click.testing import CliRunner

from quarry.store.__main__ import cli
from quarry.store.db import Database, init_db


def test_add_company_with_domain(tmp_path):
    db_path = tmp_path / "test_store.db"
    init_db(db_path)
    runner = CliRunner()
    with patch("quarry.store.__main__.settings") as mock_settings:
        mock_settings.db_path = str(db_path)
        result = runner.invoke(
            cli, ["add-company", "--name", "Test Corp", "--domain", "test.com"]
        )
    assert result.exit_code == 0

    db = Database(db_path)
    companies = db.get_all_companies(active_only=False)
    assert len(companies) == 1
    assert companies[0].domain == "test.com"


def test_add_company_with_careers_url(tmp_path):
    db_path = tmp_path / "test_store.db"
    init_db(db_path)
    runner = CliRunner()
    with patch("quarry.store.__main__.settings") as mock_settings:
        mock_settings.db_path = str(db_path)
        result = runner.invoke(
            cli,
            [
                "add-company",
                "--name",
                "Test Corp",
                "--careers-url",
                "https://boards.greenhouse.io/testcorp",
            ],
        )
    assert result.exit_code == 0

    db = Database(db_path)
    companies = db.get_all_companies(active_only=False)
    assert len(companies) == 1
    assert companies[0].ats_type == "greenhouse"
    assert companies[0].ats_slug == "testcorp"
    assert companies[0].resolve_status == "resolved"
