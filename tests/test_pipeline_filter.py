"""Tests for similarity filter and keyword blocklist."""

import numpy as np
import pytest

from quarry.models import (
    FilterResult,
    JobPosting,
    ParsedLocation,
    ParseResult,
    RawPosting,
)
from quarry.pipeline.filter import (
    apply_keyword_blocklist,
    apply_location_filter,
    cosine_similarity,
    filter_posting,
    score_similarity,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = np.array([1.0, 0.0, 0.0])
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        v1 = np.array([1.0, 0.0, 0.0])
        v2 = np.array([0.0, 1.0, 0.0])
        assert cosine_similarity(v1, v2) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        v1 = np.array([1.0, 0.0])
        v2 = np.array([-1.0, 0.0])
        assert cosine_similarity(v1, v2) == pytest.approx(-1.0)

    def test_similarity_range(self):
        v1 = np.random.rand(384)
        v2 = np.random.rand(384)
        sim = cosine_similarity(v1, v2)
        assert -1.0 <= sim <= 1.0

    def test_zero_vector_returns_zero(self):
        v1 = np.zeros(384)
        v2 = np.random.rand(384)
        assert cosine_similarity(v1, v2) == 0.0


class TestScoreSimilarity:
    def test_relevant_posting_high_score(self):
        ideal = np.random.rand(384).astype(np.float32)
        ideal = ideal / np.linalg.norm(ideal)
        posting_emb = ideal * 0.95 + np.random.rand(384) * 0.05
        posting_emb = posting_emb / np.linalg.norm(posting_emb)

        score = score_similarity(posting_emb, ideal)
        assert score > 0.9

    def test_irrelevant_posting_low_score(self):
        ideal = np.zeros(384, dtype=np.float32)
        ideal[0] = 1.0

        irrelevant = np.zeros(384, dtype=np.float32)
        irrelevant[100] = 1.0

        score = score_similarity(irrelevant, ideal)
        assert score < 0.2

    def test_identical_vectors_score_one(self):
        v = np.random.rand(384).astype(np.float32)
        v = v / np.linalg.norm(v)
        assert score_similarity(v, v) == pytest.approx(1.0, abs=1e-5)


class TestApplyKeywordBlocklist:
    def test_blocklisted_keyword_in_title(self):
        posting = RawPosting(
            company_id=1,
            title="Staffing Agency Recruiter",
            url="https://example.com/1",
            source_type="greenhouse",
        )
        blocklist = ["staffing agency"]
        assert apply_keyword_blocklist(posting, blocklist) is False

    def test_blocklisted_keyword_in_description(self):
        posting = RawPosting(
            company_id=1,
            title="Engineer",
            url="https://example.com/2",
            description="This role requires clearance",
            source_type="greenhouse",
        )
        blocklist = ["requires clearance"]
        assert apply_keyword_blocklist(posting, blocklist) is False

    def test_no_blocklist_match(self):
        posting = RawPosting(
            company_id=1,
            title="Senior Engineer",
            url="https://example.com/3",
            description="Build great products",
            source_type="greenhouse",
        )
        blocklist = ["staffing agency", "relocation required"]
        assert apply_keyword_blocklist(posting, blocklist) is True

    def test_case_insensitive_match(self):
        posting = RawPosting(
            company_id=1,
            title="STAFFING AGENCY recruiter",
            url="https://example.com/4",
            source_type="lever",
        )
        blocklist = ["staffing agency"]
        assert apply_keyword_blocklist(posting, blocklist) is False

    def test_empty_blocklist_passes(self):
        posting = RawPosting(
            company_id=1,
            title="Anything goes",
            url="https://example.com/5",
            source_type="greenhouse",
        )
        assert apply_keyword_blocklist(posting, []) is True

    def test_partial_match_is_not_blocked(self):
        posting = RawPosting(
            company_id=1,
            title="Remote staffing coordinator",
            url="https://example.com/6",
            description="Internal team, not an agency",
            source_type="greenhouse",
        )
        blocklist = ["staffing agency"]
        assert apply_keyword_blocklist(posting, blocklist) is True

    def test_blocklisted_in_location(self):
        posting = RawPosting(
            company_id=1,
            title="Engineer",
            url="https://example.com/7",
            location="Relocation required - San Francisco",
            source_type="greenhouse",
        )
        blocklist = ["relocation required"]
        assert apply_keyword_blocklist(posting, blocklist) is False


class TestFilterPosting:
    def test_passes_relevant_posting(self):
        from unittest.mock import patch

        raw = RawPosting(
            company_id=1,
            title="Senior People Analytics Manager",
            url="https://example.com/1",
            description="Lead analytics team",
            source_type="greenhouse",
        )
        ideal_emb = np.random.rand(384).astype(np.float32)
        ideal_emb = ideal_emb / np.linalg.norm(ideal_emb)

        with patch("quarry.pipeline.filter.embed_posting") as mock_embed:
            mock_embed.return_value = ideal_emb
            result = filter_posting(raw, ideal_emb, threshold=0.3, blocklist=[])

        assert isinstance(result, FilterResult)
        assert result.passed is True
        assert result.skip_reason is None
        assert result.similarity_score is not None

    def test_blocks_low_similarity(self):
        from unittest.mock import patch

        raw = RawPosting(
            company_id=1,
            title="Line Cook",
            url="https://example.com/2",
            description="Prepare meals in kitchen",
            source_type="lever",
        )
        ideal_emb = np.zeros(384, dtype=np.float32)
        ideal_emb[0] = 1.0

        posting_emb = np.zeros(384, dtype=np.float32)
        posting_emb[200] = 1.0

        with patch("quarry.pipeline.filter.embed_posting") as mock_embed:
            mock_embed.return_value = posting_emb
            result = filter_posting(raw, ideal_emb, threshold=0.58, blocklist=[])

        assert result.passed is False
        assert result.skip_reason == "low_similarity"

    def test_blocks_blocklisted_keyword(self):
        from unittest.mock import patch

        raw = RawPosting(
            company_id=1,
            title="Staffing Agency Recruiter",
            url="https://example.com/3",
            description="Recruit for staffing agency",
            source_type="greenhouse",
        )
        ideal_emb = np.ones(384, dtype=np.float32)
        ideal_emb = ideal_emb / np.linalg.norm(ideal_emb)

        with patch("quarry.pipeline.filter.embed_posting") as mock_embed:
            mock_embed.return_value = ideal_emb.copy()
            result = filter_posting(
                raw, ideal_emb, threshold=0.3, blocklist=["staffing agency"]
            )

        assert result.passed is False
        assert result.skip_reason == "blocklist"

    def test_returns_similarity_score_even_on_block(self):
        from unittest.mock import patch

        raw = RawPosting(
            company_id=1,
            title="Staffing Agency Role",
            url="https://example.com/4",
            source_type="greenhouse",
        )
        ideal_emb = np.ones(384, dtype=np.float32)
        ideal_emb = ideal_emb / np.linalg.norm(ideal_emb)

        with patch("quarry.pipeline.filter.embed_posting") as mock_embed:
            mock_embed.return_value = ideal_emb.copy()
            result = filter_posting(
                raw, ideal_emb, threshold=0.3, blocklist=["staffing agency"]
            )

        assert result.similarity_score is not None


class TestApplyLocationFilter:
    def test_no_filter_config_passes_all(self):
        posting = JobPosting(
            company_id=1, title="Eng", title_hash="h", url="https://example.com"
        )
        parse_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="New York, NY",
                    city="New York",
                    state_code="NY",
                    country_code="US",
                    region="US-East",
                )
            ],
        )
        passed, reason = apply_location_filter(posting, parse_result, settings=None)
        assert passed is True

    def test_accept_remote_passes(self):
        posting = JobPosting(
            company_id=1, title="Eng", title_hash="h", url="https://example.com"
        )
        parse_result = ParseResult(work_model="remote", locations=[])
        settings = {"location_filter": {"accept_remote": True}}
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is True

    def test_reject_non_remote_when_no_accept_remote(self):
        posting = JobPosting(
            company_id=1, title="Eng", title_hash="h", url="https://example.com"
        )
        parse_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="Chicago, IL",
                    city="Chicago",
                    state_code="IL",
                    country_code="US",
                    region="US-Central",
                )
            ],
        )
        settings = {
            "location_filter": {
                "accept_remote": False,
                "accept_nearby": True,
                "nearby_cities": ["SF"],
            }
        }
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is False
        assert reason == "location"

    def test_accept_nearby_matching_city(self):
        posting = JobPosting(
            company_id=1, title="Eng", title_hash="h", url="https://example.com"
        )
        parse_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="San Francisco, CA",
                    city="San Francisco",
                    state_code="CA",
                    country_code="US",
                    region="US-West",
                )
            ],
        )
        settings = {
            "location_filter": {
                "accept_nearby": True,
                "nearby_cities": ["San Francisco"],
            }
        }
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is True

    def test_reject_non_nearby(self):
        posting = JobPosting(
            company_id=1, title="Eng", title_hash="h", url="https://example.com"
        )
        parse_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="New York, NY",
                    city="New York",
                    state_code="NY",
                    country_code="US",
                    region="US-East",
                )
            ],
        )
        settings = {
            "location_filter": {
                "accept_nearby": True,
                "nearby_cities": ["San Francisco"],
            }
        }
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is False
        assert reason == "location"

    def test_empty_locations_passes(self):
        posting = JobPosting(
            company_id=1, title="Eng", title_hash="h", url="https://example.com"
        )
        parse_result = ParseResult(work_model=None, locations=[])
        settings = {
            "location_filter": {
                "accept_nearby": True,
                "nearby_cities": ["San Francisco"],
            }
        }
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is True

    def test_accept_regions_matching(self):
        posting = JobPosting(
            company_id=1, title="Eng", title_hash="h", url="https://example.com"
        )
        parse_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="Portland, OR",
                    city="Portland",
                    state_code="OR",
                    country_code="US",
                    region="US-West",
                )
            ],
        )
        settings = {
            "location_filter": {
                "accept_nearby": True,
                "nearby_cities": ["San Francisco"],
                "accept_regions": ["US-West"],
            }
        }
        passed, reason = apply_location_filter(posting, parse_result, settings=settings)
        assert passed is True
