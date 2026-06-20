import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from quarry.agent.scheduler import (
    _process_posting,
    resolve_or_create_search_company,
    run_once,
)
from quarry.config import (
    CompanyFilterConfig,
    FiltersConfig,
    KeywordBlocklistConfig,
    LocationFilterConfig,
)
from quarry.crawlers.jobspy_client import JobSpyCompanyHints
from quarry.models import Company, RawPosting, UserWatchlistItem
from quarry.pipeline.embedder import set_ideal_embedding
from quarry.store.db import init_db

EMBEDDING_DIM = 384


@pytest.fixture(autouse=True)
def _mock_embedding_model():
    """Prevent tests from loading the real sentence-transformers model.

    Scheduler pipeline tests use crawler mocks and should not depend on
    a cached model or network access to HuggingFace.  Random embeddings
    are sufficient for testing filter/dedup/store logic.
    """
    with patch("quarry.pipeline.embedder._get_model") as mock_get_model:
        mock_model = MagicMock()
        mock_model.get_embedding_dimension.return_value = EMBEDDING_DIM

        def _fake_encode(text, normalize_embeddings=True, show_progress_bar=False):
            emb = np.random.rand(EMBEDDING_DIM).astype(np.float32)
            if normalize_embeddings:
                emb = emb / (np.linalg.norm(emb) + 1e-9)
            return emb

        mock_model.encode.side_effect = _fake_encode
        mock_get_model.return_value = mock_model
        yield


@pytest.fixture
def db(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def seeded_db(db):
    company = Company(name="TestCorp", ats_type="greenhouse", ats_slug="testcorp")
    db.insert_company(company)
    return db


def _make_raw_posting(
    company_id=1, title="Senior Data Analyst", url="https://example.com/job/1"
):
    return RawPosting(
        company_id=company_id,
        title=title,
        url=url,
        description="Analyze people data and build dashboards",
        location="Remote, US",
        source_type="greenhouse",
    )


class TestRunOnce:
    def test_run_once_logs_ingest_filter_summary(self, seeded_db, caplog):
        mock_postings = [
            _make_raw_posting(title="Senior Engineer"),
            _make_raw_posting(title="Senior Data Analyst"),
        ]

        with (
            patch("quarry.agent.scheduler._crawl_company") as mock_crawl,
            patch("quarry.agent.scheduler._crawl_search_queries") as mock_search,
            patch(
                "quarry.agent.scheduler.settings.filters",
                FiltersConfig(
                    keyword_blocklist=KeywordBlocklistConfig(keywords=["Engineer"])
                ),
            ),
        ):
            mock_crawl.return_value = mock_postings
            mock_search.return_value = []

            set_ideal_embedding(seeded_db, "Senior people analytics leader role")

            with caplog.at_level(logging.INFO, logger="quarry.agent.scheduler"):
                summary = run_once(seeded_db)

            assert summary["total_filtered"] == 1
            summary_lines = [
                rec.message
                for rec in caplog.records
                if "Ingest filter summary:" in rec.message
            ]
            assert len(summary_lines) == 1
            assert "blocklist=1" in summary_lines[0]

    def test_run_once_filter_summary_excludes_location(self, seeded_db, caplog):
        mock_postings = [
            _make_raw_posting(title="Senior Engineer"),
        ]

        with (
            patch("quarry.agent.scheduler._crawl_company") as mock_crawl,
            patch("quarry.agent.scheduler._crawl_search_queries") as mock_search,
            patch(
                "quarry.agent.scheduler.settings.filters",
                FiltersConfig(
                    keyword_blocklist=KeywordBlocklistConfig(keywords=["Engineer"])
                ),
            ),
        ):
            mock_crawl.return_value = mock_postings
            mock_search.return_value = []

            set_ideal_embedding(seeded_db, "Senior people analytics leader role")

            with caplog.at_level(logging.INFO, logger="quarry.agent.scheduler"):
                run_once(seeded_db)

            summary_lines = [
                rec.message
                for rec in caplog.records
                if "Ingest filter summary:" in rec.message
            ]
            assert len(summary_lines) == 1
            assert "location=" not in summary_lines[0]

    def test_run_once_processes_companies(self, seeded_db):
        mock_postings = [_make_raw_posting()]

        with (
            patch("quarry.agent.scheduler._crawl_company") as mock_crawl,
            patch("quarry.agent.scheduler._crawl_search_queries") as mock_search,
        ):
            mock_crawl.return_value = mock_postings
            mock_search.return_value = []

            set_ideal_embedding(seeded_db, "Senior people analytics leader role")

            summary = run_once(seeded_db)

            assert summary["companies_crawled"] >= 1
            assert summary["total_found"] >= 1
            postings = seeded_db.get_postings()
            assert len(postings) >= 1
            # similarity_score is now on user_similarity_scores, not JobPosting
            rows = seeded_db.get_postings_with_scores(status="new", limit=10)
            assert any(r["similarity_score"] is not None for r in rows)

    def test_run_once_skips_duplicates(self, seeded_db):
        mock_postings = [_make_raw_posting()]

        with (
            patch("quarry.agent.scheduler._crawl_company") as mock_crawl,
            patch("quarry.agent.scheduler._crawl_search_queries") as mock_search,
        ):
            mock_crawl.return_value = mock_postings
            mock_search.return_value = []

            set_ideal_embedding(seeded_db, "Senior people analytics leader role")

            run_once(seeded_db)

            mock_crawl.return_value = [_make_raw_posting()]
            summary = run_once(seeded_db)
            assert summary["total_new"] == 0

    def test_run_once_logs_crawl_run(self, seeded_db):
        mock_postings = [_make_raw_posting()]

        with (
            patch("quarry.agent.scheduler._crawl_company") as mock_crawl,
            patch("quarry.agent.scheduler._crawl_search_queries") as mock_search,
        ):
            mock_crawl.return_value = mock_postings
            mock_search.return_value = []

            set_ideal_embedding(seeded_db, "Senior people analytics leader role")

            run_once(seeded_db)

            from quarry.store.models import CrawlRun as ORMCrawlRun
            from quarry.store.session import session_scope

            with session_scope(engine=seeded_db.engine) as session:
                from sqlalchemy import select as sa_select

                runs = session.execute(sa_select(ORMCrawlRun)).scalars().all()
                assert len(runs) >= 1


class TestProcessPosting:
    def test_process_posting_new_job_stored(self, db, seeded_db):
        """Posting passes all filters -> status='new', similarity computed"""
        raw = RawPosting(
            company_id=1,
            title="Senior Data Analyst",
            url="https://example.com/job/1",
            description="Analyze people data and build dashboards",
            location="Remote, US",
            source_type="greenhouse",
        )
        ideal_embedding = np.random.rand(384).astype(np.float32)
        ideal_embedding = ideal_embedding / np.linalg.norm(ideal_embedding)

        posting, status, similarity, parse_result = _process_posting(
            raw, db, "TestCorp", None, ideal_embedding
        )
        assert status == "new"
        assert posting is not None
        assert similarity >= -1.0

    def test_process_posting_blocklist_rejected(self, db):
        """Keyword blocklist rejects -> status='blocklist'"""
        config = FiltersConfig(
            keyword_blocklist=KeywordBlocklistConfig(keywords=["engineer"])
        )
        raw = RawPosting(
            company_id=1,
            title="Senior Engineer",
            url="https://example.com/job/2",
            source_type="test",
        )
        ideal_embedding = np.ones(384, dtype=np.float32)
        ideal_embedding = ideal_embedding / np.linalg.norm(ideal_embedding)
        posting, status, similarity, parse_result = _process_posting(
            raw, db, "Acme Corp", config, ideal_embedding
        )
        assert status == "blocklist"
        assert posting is None

    def test_process_posting_company_deny(self, db):
        """Company deny list rejects -> status='company_deny'"""
        config = FiltersConfig(company_filter=CompanyFilterConfig(deny=["Talentify"]))
        raw = RawPosting(
            company_id=1,
            title="Recruiter",
            url="https://example.com/job/3",
            source_type="test",
        )
        ideal_embedding = np.ones(384, dtype=np.float32)
        ideal_embedding = ideal_embedding / np.linalg.norm(ideal_embedding)
        posting, status, similarity, parse_result = _process_posting(
            raw, db, "Talentify", config, ideal_embedding
        )
        assert status == "company_deny"

    def test_process_posting_duplicate(self, db, seeded_db):
        """Duplicate posting -> status='duplicate'"""
        raw = _make_raw_posting(company_id=1)
        ideal_embedding = np.ones(384, dtype=np.float32)
        ideal_embedding = ideal_embedding / np.linalg.norm(ideal_embedding)

        posting, status, sim, pr = _process_posting(
            raw, db, "TestCorp", None, ideal_embedding
        )
        assert status == "new"
        db.insert_posting(posting)

        posting2, status2, sim2, pr2 = _process_posting(
            raw, db, "TestCorp", None, ideal_embedding
        )
        assert status2 == "duplicate"

    def test_ingest_no_longer_filters_location(self, db):
        """A posting that the old LocationFilter would have rejected
        now passes ingest (location filtering moved to read-time)."""
        config = FiltersConfig(
            location_filter=LocationFilterConfig(
                target_location=["San Francisco, CA"],
                accept_remote=False,
            )
        )
        config.normalize_config()
        raw = RawPosting(
            company_id=1,
            title="Backend Engineer",
            url="https://example.com/job/irvine",
            description="Build APIs",
            location="Irvine, CA",
            source_type="test",
        )
        ideal_embedding = np.ones(384, dtype=np.float32)
        ideal_embedding = ideal_embedding / np.linalg.norm(ideal_embedding)
        posting, status, similarity, parse_result = _process_posting(
            raw, db, "TestCorp", config, ideal_embedding
        )
        # Ingest no longer filters by location -> status is 'new'
        assert status == "new"
        assert posting is not None
        assert similarity >= 0.0


class TestResolveOrCreateSearchCompany:
    def test_creates_company_in_shared_table(self, db):
        hints = JobSpyCompanyHints(
            domain_hint=None, ats_type_hint=None, ats_slug_hint=None
        )
        result = resolve_or_create_search_company(db, "NovelCo", hints, user_id=1)

        assert result.name == "NovelCo"
        assert result.resolve_status == "unresolved"

        # Verify in shared table
        fetched = db.get_company_by_name("NovelCo")
        assert fetched is not None

        # Verify watchlist entry
        wl = db.get_watchlist_item(1, result.id)
        assert wl is not None
        assert wl.active is False
        assert wl.added_reason == "search"

    def test_uses_hints(self, db):
        hints = JobSpyCompanyHints(
            domain_hint="acme.com",
            ats_type_hint="greenhouse",
            ats_slug_hint="acme",
        )
        result = resolve_or_create_search_company(db, "Acme", hints, user_id=1)

        assert result.domain == "acme.com"
        assert result.ats_type == "greenhouse"
        assert result.ats_slug == "acme"
        assert result.resolve_status == "resolved"
        assert result.careers_url == "https://boards.greenhouse.io/acme"

    def test_returns_existing_does_not_overwrite_watchlist(self, db):
        company = Company(name="ExistingCo")
        company.id = db.insert_company(company)

        # Seed company already in watchlist (active)
        db.upsert_watchlist_item(
            UserWatchlistItem(
                user_id=1, company_id=company.id, active=True, added_reason="seed"
            )
        )

        hints = JobSpyCompanyHints(
            domain_hint=None, ats_type_hint=None, ats_slug_hint=None
        )
        result = resolve_or_create_search_company(db, "ExistingCo", hints, user_id=1)

        assert result.id == company.id

        # Watchlist should NOT be overwritten to inactive/search
        wl = db.get_watchlist_item(1, company.id)
        assert wl.active is True
        assert wl.added_reason == "seed"
