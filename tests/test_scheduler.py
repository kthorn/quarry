from unittest.mock import patch

import pytest

from quarry.agent.scheduler import run_once
from quarry.models import Company, RawPosting
from quarry.pipeline.embedder import set_ideal_embedding
from quarry.store.db import init_db


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
            assert postings[0].similarity_score is not None

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

            runs = seeded_db.execute("SELECT * FROM crawl_runs")
            assert len(runs) >= 1
