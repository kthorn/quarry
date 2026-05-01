# tests/test_orm.py
"""Tests for SQLAlchemy ORM models (Phase 2).

Verifies:
- All models import and instantiate correctly
- Relationships can be navigated (eager/lazy loading)
- Session management (commit, rollback, cascade)
- Unique/CHECK constraints enforced through ORM
- The default user seed fires correctly
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quarry.store.db import init_db
from quarry.store.models import (
    AgentAction,
    Base,
    ClassifierVersion,
    Company,
    CrawlRun,
    JobPosting,
    JobPostingLocation,
    Location,
    SystemSetting,
    User,
    UserClassifierScore,
    UserEnrichedPosting,
    UserLabel,
    UserPostingStatus,
    UserSearchQuery,
    UserSetting,
    UserSimilarityScore,
    UserWatchlistItem,
)
from quarry.store.session import get_engine, session_scope


@pytest.fixture
def engine(tmp_path):
    """Create a fresh on-disk SQLite DB with ORM schema."""
    db_path = tmp_path / "test_orm.db"
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def seeded(engine):
    """Engine with a default user and a company seeded via ORM."""
    with session_scope(engine=engine) as session:
        session.add(User(id=1, email="default@local", name="Default User"))
        session.add(Company(id=1, name="Acme Corp"))
    return engine


def test_all_models_importable():
    """All 17 model classes are importable and are Base subclasses."""
    models = [
        Company,
        JobPosting,
        Location,
        JobPostingLocation,
        CrawlRun,
        ClassifierVersion,
        AgentAction,
        SystemSetting,
        User,
        UserWatchlistItem,
        UserPostingStatus,
        UserLabel,
        UserSearchQuery,
        UserSimilarityScore,
        UserClassifierScore,
        UserEnrichedPosting,
        UserSetting,
    ]
    assert len(models) == 17, f"Expected 17 models, got {len(models)}"
    for model in models:
        assert issubclass(model, Base), f"{model.__name__} not a Base subclass"


def test_create_and_query_company(engine):
    """Insert a company and retrieve it via ORM."""
    with session_scope(engine=engine) as session:
        company = Company(name="TestCo", domain="testco.com")
        session.add(company)
        session.flush()
        assert company.id is not None

        fetched = session.get(Company, company.id)
        assert fetched is not None
        assert fetched.name == "TestCo"
        assert fetched.domain == "testco.com"
        assert fetched.ats_type == "unknown"  # server_default
        assert fetched.resolve_status == "unresolved"  # server_default


def test_company_to_postings_relationship(seeded):
    """Company.postings relationship navigates correctly."""
    with session_scope(engine=seeded) as session:
        company = session.get(Company, 1)
        assert company is not None
        posting = JobPosting(
            company_id=1,
            title="SWE",
            title_hash="abc123",
            url="http://example.com/job/1",
        )
        company.postings.append(posting)
        session.flush()

        assert posting.company_id == 1
        assert posting.company.name == "Acme Corp"

        assert len(company.postings) == 1
        assert company.postings[0].title == "SWE"


def test_cascade_delete_company_removes_postings(seeded):
    """Deleting a company cascades to its postings."""
    with session_scope(engine=seeded) as session:
        company = session.get(Company, 1)
        assert company is not None
        posting = JobPosting(
            company_id=1, title="SWE", title_hash="abc", url="http://x.com"
        )
        company.postings.append(posting)
        session.flush()
        posting_id = posting.id

    with session_scope(engine=seeded) as session:
        company = session.get(Company, 1)
        assert company is not None
        session.delete(company)
        session.commit()

    with session_scope(engine=seeded) as session:
        result = session.get(JobPosting, posting_id)
        assert result is None


def test_per_user_label_isolation(seeded):
    """UserLabel queries are isolated by user_id."""
    posting_id = None
    with session_scope(engine=seeded) as session:
        session.add(User(id=2, email="user2@test.com"))
        posting = JobPosting(
            company_id=1, title="SWE", title_hash="xyz", url="http://x.com"
        )
        session.add(posting)
        session.flush()
        posting_id = posting.id

        session.add(UserLabel(user_id=1, posting_id=posting_id, signal="positive"))
        session.add(UserLabel(user_id=2, posting_id=posting_id, signal="negative"))
        session.commit()

    with session_scope(engine=seeded) as session:
        u1_labels = session.execute(
            select(UserLabel.signal).where(
                UserLabel.user_id == 1,
                UserLabel.posting_id == posting_id,
            )
        ).all()
        assert len(u1_labels) == 1
        assert u1_labels[0][0] == "positive"

    with session_scope(engine=seeded) as session:
        u2_labels = session.execute(
            select(UserLabel.signal).where(
                UserLabel.user_id == 2,
                UserLabel.posting_id == posting_id,
            )
        ).all()
        assert len(u2_labels) == 1
        assert u2_labels[0][0] == "negative"


def test_check_constraint_user_labels_signal(seeded):
    """Invalid signal raises IntegrityError."""
    with session_scope(engine=seeded) as session:
        posting = JobPosting(
            company_id=1, title="SWE", title_hash="abc", url="http://x.com"
        )
        session.add(posting)
        session.flush()

        with pytest.raises(IntegrityError):
            session.add(
                UserLabel(user_id=1, posting_id=posting.id, signal="invalid_signal")
            )
            session.flush()
        session.rollback()


def test_unique_constraint_user_labels(seeded):
    """Duplicate (user_id, posting_id, signal) raises IntegrityError."""
    with session_scope(engine=seeded) as session:
        posting = JobPosting(
            company_id=1, title="SWE", title_hash="abc", url="http://x.com"
        )
        session.add(posting)
        session.flush()

        session.add(UserLabel(user_id=1, posting_id=posting.id, signal="positive"))
        session.flush()

        with pytest.raises(IntegrityError):
            session.add(UserLabel(user_id=1, posting_id=posting.id, signal="positive"))
            session.flush()
        session.rollback()


def test_default_user_seeded_by_init_db(tmp_path):
    """init_db seeds the default user (id=1)."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    engine = get_engine(db_path)
    with session_scope(engine=engine) as session:
        user = session.get(User, 1)
        assert user is not None
        assert user.email == "default@local"
        assert user.name == "Default User"
        assert user.is_active is True


def test_model_version_id_set_null_on_delete(seeded):
    """Classifier score survives model version deletion (SET NULL)."""
    with session_scope(engine=seeded) as session:
        posting = JobPosting(
            company_id=1, title="SWE", title_hash="def", url="http://x.com"
        )
        session.add(posting)
        session.add(ClassifierVersion(id=1, notes="v1"))
        session.flush()

        score = UserClassifierScore(
            user_id=1, posting_id=posting.id, classifier_score=0.9, model_version_id=1
        )
        session.add(score)
        session.flush()
        score_id = score.id
        session.commit()

    # Delete the classifier version
    with session_scope(engine=seeded) as session:
        cv = session.get(ClassifierVersion, 1)
        session.delete(cv)
        session.commit()

    # Score should survive with model_version_id set to NULL
    with session_scope(engine=seeded) as session:
        score = session.get(UserClassifierScore, score_id)
        assert score is not None
        assert score.classifier_score == 0.9
        assert score.model_version_id is None


def test_check_constraint_companies_ats_type(seeded):
    """Invalid ats_type raises IntegrityError."""
    with session_scope(engine=seeded) as session:
        company = Company(name="TestCo", ats_type="invalid_type")
        session.add(company)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_unique_constraint_user_watchlist(seeded):
    """Duplicate (user_id, company_id) raises IntegrityError."""
    with session_scope(engine=seeded) as session:
        session.add(UserWatchlistItem(user_id=1, company_id=1))
        session.flush()

        with pytest.raises(IntegrityError):
            session.add(UserWatchlistItem(user_id=1, company_id=1))
            session.flush()
        session.rollback()


def test_check_constraint_user_posting_status(seeded):
    """Invalid status raises IntegrityError."""
    with session_scope(engine=seeded) as session:
        posting = JobPosting(
            company_id=1, title="SWE", title_hash="ghi", url="http://x.com"
        )
        session.add(posting)
        session.flush()

        with pytest.raises(IntegrityError):
            session.add(
                UserPostingStatus(
                    user_id=1, posting_id=posting.id, status="invalid_status"
                )
            )
            session.flush()
        session.rollback()


def test_unique_constraint_user_posting_status(seeded):
    """Duplicate (user_id, posting_id) raises IntegrityError."""
    with session_scope(engine=seeded) as session:
        posting = JobPosting(
            company_id=1, title="SWE", title_hash="jkl", url="http://x.com"
        )
        session.add(posting)
        session.flush()

        session.add(UserPostingStatus(user_id=1, posting_id=posting.id))
        session.flush()

        with pytest.raises(IntegrityError):
            session.add(UserPostingStatus(user_id=1, posting_id=posting.id))
            session.flush()
        session.rollback()


def test_engine_singleton_caching(tmp_path):
    """get_engine returns the same engine for the same DB path."""
    db_path = tmp_path / "test.db"
    engine1 = get_engine(db_path)
    engine2 = get_engine(db_path)
    assert engine1 is engine2


def test_engine_different_paths_different_engines(tmp_path):
    """get_engine returns different engines for different DB paths."""
    engine1 = get_engine(tmp_path / "test1.db")
    engine2 = get_engine(tmp_path / "test2.db")
    assert engine1 is not engine2


def test_session_scope_commit(engine):
    """Changes are committed on clean exit from session_scope."""
    with session_scope(engine=engine) as session:
        session.add(Company(name="CommitCo", domain="commit.com"))

    with session_scope(engine=engine) as session:
        result = session.execute(
            select(Company).where(Company.name == "CommitCo")
        ).scalar_one()
        assert result.domain == "commit.com"


def test_session_scope_rollback(engine):
    """Changes are rolled back on exception in session_scope."""
    with pytest.raises(ValueError):
        with session_scope(engine=engine) as session:
            session.add(Company(name="RollbackCo"))
            raise ValueError("forced error")

    with session_scope(engine=engine) as session:
        result = session.execute(
            select(Company).where(Company.name == "RollbackCo")
        ).scalar_one_or_none()
        assert result is None
