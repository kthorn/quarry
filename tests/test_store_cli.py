"""Tests for quarry.store.__main__ CLI commands."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner
from sqlalchemy import text

from quarry.store.__main__ import cli
from quarry.store.db import Database, init_db
from quarry.store.session import get_engine, session_scope

# ── Existing tests (add-company) ──────────────────────────────────


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


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def seeded_db(tmp_path):
    """Create a temp database with test data for reset tests.

    Returns (db_path, models_dir) tuple.
    """
    db_path = tmp_path / "test.db"
    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # Create a dummy .pkl file
    pkl_file = models_dir / "classifier_1_v1.pkl"
    pkl_file.write_bytes(b"dummy")

    # Initialize DB (creates schema + default user)
    init_db(db_path)
    engine = get_engine(db_path)

    with session_scope(engine=engine) as session:
        from quarry.store.models import (
            ClassifierVersion,
            Company,
            CrawlRun,
            JobPosting,
            UserClassifierScore,
            UserPostingState,
            UserSearchQuery,
            UserSetting,
        )

        # Add a company
        co = Company(name="TestCo", domain="test.com", ats_type="unknown")
        session.add(co)
        session.flush()
        company_id = co.id

        # Add a posting
        jp = JobPosting(
            company_id=company_id,
            title="Test Job",
            title_hash="hash1",
            url="http://test.com/job1",
        )
        session.add(jp)
        session.flush()
        posting_id = jp.id

        # Add a crawl run
        cr = CrawlRun(company_id=company_id, status="completed")
        session.add(cr)

        # Add a label (user_posting_state)
        state = UserPostingState(user_id=1, posting_id=posting_id, interest=True)
        session.add(state)

        # Add user settings
        us = UserSetting(user_id=1, key="test_key", value="test_value")
        session.add(us)

        # Add search query
        sq = UserSearchQuery(user_id=1, query_text="test query")
        session.add(sq)

        # Add classifier version + user classifier score (FK-safe order test)
        cv = ClassifierVersion()
        session.add(cv)
        session.flush()
        cv_id = cv.id

        ucs = UserClassifierScore(
            user_id=1,
            posting_id=posting_id,
            classifier_score=0.5,
            model_version_id=cv_id,
        )
        session.add(ucs)

    return db_path, models_dir


def _count_table(engine, table_name: str) -> int:
    """Count rows in a table via raw SQL."""
    with session_scope(engine=engine) as session:
        result: int = (
            session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0
        )
        return result


def _get_users(engine) -> list[dict]:
    """Get all user rows."""
    with session_scope(engine=engine) as session:
        rows = session.execute(text("SELECT id, email, name FROM users")).fetchall()
        return [{"id": r[0], "email": r[1], "name": r[2]} for r in rows]


# ── Tests: reset --keep-companies --yes ──────────────────────────


def test_reset_keep_companies_clears_posting_derived_tables(seeded_db):
    """reset --keep-companies --yes empties posting-derived tables."""
    db_path, models_dir = seeded_db
    engine = get_engine(db_path)

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset", "--keep-companies", "--yes"])

    assert result.exit_code == 0

    # Posting-derived tables must be empty
    assert _count_table(engine, "job_postings") == 0
    assert _count_table(engine, "user_posting_state") == 0
    assert _count_table(engine, "crawl_runs") == 0
    assert _count_table(engine, "user_classifier_scores") == 0
    assert _count_table(engine, "classifier_versions") == 0
    assert _count_table(engine, "user_similarity_scores") == 0
    assert _count_table(engine, "user_ranking_scores") == 0
    assert _count_table(engine, "user_enriched_postings") == 0
    assert _count_table(engine, "job_posting_locations") == 0


def test_reset_keep_companies_preserves_company_tables(seeded_db):
    """reset --keep-companies --yes keeps company infrastructure."""
    db_path, models_dir = seeded_db
    engine = get_engine(db_path)

    # Pre-counts
    pre_companies = _count_table(engine, "companies")
    assert pre_companies == 1

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset", "--keep-companies", "--yes"])

    assert result.exit_code == 0

    # Companies unchanged
    assert _count_table(engine, "companies") == pre_companies
    # User settings unchanged (we seeded one)
    assert _count_table(engine, "user_settings") == 1
    # Search queries unchanged (we seeded one)
    assert _count_table(engine, "user_search_queries") == 1
    # Default user still present
    users = _get_users(engine)
    assert len(users) == 1
    assert users[0]["id"] == 1
    assert users[0]["email"] == "default@local"


def test_reset_keep_companies_removes_pkl_files(seeded_db):
    """reset --keep-companies --yes removes classifier_*.pkl files."""
    db_path, models_dir = seeded_db

    # Verify .pkl exists before reset
    pkl_files = list(models_dir.glob("classifier_*.pkl"))
    assert len(pkl_files) == 1

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset", "--keep-companies", "--yes"])

    assert result.exit_code == 0

    # .pkl removed
    pkl_files = list(models_dir.glob("classifier_*.pkl"))
    assert len(pkl_files) == 0


# ── Tests: reset --yes (full) ────────────────────────────────────


def test_reset_full_clears_all_tables(seeded_db):
    """reset --yes (full) empties every table except users (re-seeded)."""
    db_path, models_dir = seeded_db
    engine = get_engine(db_path)

    from quarry.store.models import Base

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset", "--yes"])

    assert result.exit_code == 0

    # Every table in Base.metadata must be empty except users (re-seeded)
    for table in Base.metadata.sorted_tables:
        name = table.name
        count = _count_table(engine, name)
        if name == "users":
            assert count == 1, (
                f"Table {name} should have 1 row (re-seeded), got {count}"
            )
        else:
            assert count == 0, f"Table {name} should be empty, got {count}"

    # Verify the re-seeded default user row
    users = _get_users(engine)
    assert users[0]["id"] == 1
    assert users[0]["email"] == "default@local"
    assert users[0]["name"] == "Default User"


def test_reset_full_reseeds_default_user(seeded_db):
    """reset --yes re-seeds the default user after full wipe."""
    db_path, models_dir = seeded_db
    engine = get_engine(db_path)

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset", "--yes"])

    assert result.exit_code == 0

    # Default user re-seeded
    users = _get_users(engine)
    assert len(users) == 1
    assert users[0]["id"] == 1
    assert users[0]["email"] == "default@local"
    assert users[0]["name"] == "Default User"


def test_reset_full_removes_pkl_files(seeded_db):
    """reset --yes removes classifier_*.pkl files."""
    db_path, models_dir = seeded_db

    # Verify .pkl exists before reset
    pkl_files = list(models_dir.glob("classifier_*.pkl"))
    assert len(pkl_files) == 1

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset", "--yes"])

    assert result.exit_code == 0

    # .pkl removed
    pkl_files = list(models_dir.glob("classifier_*.pkl"))
    assert len(pkl_files) == 0


# ── Tests: reset without --yes (confirmation) ────────────────────


def test_reset_accepts_correct_answer(seeded_db):
    """reset --keep-companies without --yes accepts 'reset' at prompt."""
    db_path, models_dir = seeded_db
    engine = get_engine(db_path)

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset", "--keep-companies"], input="reset\n")

    assert result.exit_code == 0
    # Output acknowledges proceeding (deletion count lines)
    assert "Deleted" in result.output
    # .pkl removal acknowledged
    assert "Removed" in result.output

    # Posting-derived tables empty
    assert _count_table(engine, "job_postings") == 0
    assert _count_table(engine, "user_posting_state") == 0
    assert _count_table(engine, "user_classifier_scores") == 0
    assert _count_table(engine, "classifier_versions") == 0
    assert _count_table(engine, "crawl_runs") == 0
    assert _count_table(engine, "user_similarity_scores") == 0
    assert _count_table(engine, "user_ranking_scores") == 0
    assert _count_table(engine, "user_enriched_postings") == 0
    assert _count_table(engine, "job_posting_locations") == 0

    # Company-infrastructure tables preserved
    assert _count_table(engine, "companies") == 1
    assert _count_table(engine, "user_settings") == 1
    assert _count_table(engine, "user_search_queries") == 1

    # Default user still present
    users = _get_users(engine)
    assert len(users) == 1
    assert users[0]["id"] == 1
    assert users[0]["email"] == "default@local"

    # .pkl removed
    assert len(list(models_dir.glob("classifier_*.pkl"))) == 0


def test_reset_declines_on_empty_input(seeded_db):
    """reset without --yes and empty stdin declines to proceed."""
    db_path, models_dir = seeded_db
    engine = get_engine(db_path)

    # Pre-counts for comparison
    pre_postings = _count_table(engine, "job_postings")
    pre_companies = _count_table(engine, "companies")
    assert pre_postings == 1
    assert pre_companies == 1

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset"], input="")

    assert result.exit_code != 0
    # DB unchanged
    assert _count_table(engine, "job_postings") == pre_postings
    assert _count_table(engine, "companies") == pre_companies
    # .pkl still present
    assert len(list(models_dir.glob("classifier_*.pkl"))) == 1


def test_reset_declines_on_wrong_answer(seeded_db):
    """reset without --yes declines when user types anything other than 'reset'."""
    db_path, models_dir = seeded_db
    engine = get_engine(db_path)

    pre_postings = _count_table(engine, "job_postings")
    assert pre_postings == 1

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset"], input="no")

    assert result.exit_code != 0
    # DB unchanged
    assert _count_table(engine, "job_postings") == pre_postings
    # .pkl still present
    assert len(list(models_dir.glob("classifier_*.pkl"))) == 1


def test_reset_keep_companies_declines_on_wrong_answer(seeded_db):
    """reset --keep-companies without --yes declines on wrong answer."""
    db_path, models_dir = seeded_db
    engine = get_engine(db_path)

    pre_postings = _count_table(engine, "job_postings")
    assert pre_postings == 1

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset", "--keep-companies"], input="nope")

    assert result.exit_code != 0
    # DB unchanged
    assert _count_table(engine, "job_postings") == pre_postings


def test_reset_with_yes_and_correct_answer_proceeds(seeded_db):
    """reset with --yes flag skips confirmation and proceeds."""
    db_path, models_dir = seeded_db
    engine = get_engine(db_path)

    runner = CliRunner()
    with (
        patch("quarry.store.__main__.settings") as mock_settings,
        patch("quarry.store.__main__._MODELS_DIR", models_dir),
    ):
        mock_settings.db_path = str(db_path)
        result = runner.invoke(cli, ["reset", "--keep-companies", "--yes"])

    assert result.exit_code == 0
    assert _count_table(engine, "job_postings") == 0


# ── Tests: non-existent db path ──────────────────────────────────


def test_reset_refuses_nonexistent_db(tmp_path):
    """reset exits non-zero when db_path points to a non-existent file."""
    nonexistent_path = tmp_path / "does_not_exist.db"
    assert not nonexistent_path.exists()

    runner = CliRunner()
    with patch("quarry.store.__main__.settings") as mock_settings:
        mock_settings.db_path = str(nonexistent_path)
        result = runner.invoke(cli, ["reset", "--yes"])

    assert result.exit_code != 0
    assert (
        "not found" in result.output.lower()
        or "does not exist" in result.output.lower()
    )
    # No Python traceback (Click handles cleanly)
    assert "Traceback" not in result.output
