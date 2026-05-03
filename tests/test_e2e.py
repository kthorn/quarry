"""End-to-end test: seed -> crawl (mocked) -> extract -> embed -> filter -> store -> digest."""

from unittest.mock import patch

import pytest
import yaml

from quarry.models import RawPosting
from quarry.store.db import init_db

pytestmark = pytest.mark.skip(
    reason="Phase 4 — production code needs per-user field updates"
)


@pytest.fixture
def db(tmp_path):
    return init_db(tmp_path / "test.db")


@pytest.fixture
def seed_file(tmp_path):
    """Create a minimal seed file for testing."""
    data = {
        "companies": [
            {"name": "TestCorp", "ats_type": "greenhouse", "ats_slug": "testcorp"},
        ],
        "search_queries": [
            {"query_text": "People Analytics", "added_reason": "Test"},
        ],
    }
    path = tmp_path / "seed_data.yaml"
    path.write_text(yaml.dump(data))
    return str(path)


class TestEndToEnd:
    def test_seed_crawl_digest(self, db, tmp_path, seed_file):
        """Full pipeline: seed -> crawl (mocked) -> process -> store -> digest."""
        from quarry.agent.scheduler import run_once
        from quarry.agent.tools import seed as do_seed
        from quarry.digest.digest import build_digest, mark_digest_seen, write_digest
        from quarry.pipeline.embedder import set_ideal_embedding

        do_seed(db, seed_file)
        set_ideal_embedding(db, "Senior people analytics or HR technology leader")

        mock_posting = RawPosting(
            company_id=1,
            title="Senior People Analytics Manager",
            url="https://example.com/job/e2e1",
            description="Lead the people analytics function at our company. Build dashboards and drive insights.",
            location="Remote, US",
            source_type="greenhouse",
        )

        with (
            patch("quarry.agent.scheduler._crawl_company") as mock_crawl,
            patch("quarry.agent.scheduler._crawl_search_queries") as mock_search,
        ):
            mock_crawl.return_value = [mock_posting]
            mock_search.return_value = []

            summary = run_once(db)

        assert summary["total_found"] >= 1
        assert summary["total_new"] >= 1

        entries = build_digest(db, limit=10)
        assert len(entries) >= 1

        output = tmp_path / "e2e_digest.txt"
        write_digest(entries, str(output))
        assert output.exists()

        content = output.read_text()
        assert "Senior People Analytics Manager" in content

        mark_digest_seen(db, entries)
        new_entries = build_digest(db, limit=10)
        assert len(new_entries) == 0
