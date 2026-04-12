"""Tests for similarity scoring and filter pipeline."""

import numpy as np
import pytest

from quarry.config import (
    CompanyFilterConfig,
    KeywordBlocklistConfig,
    LocationFilterConfig,
)
from quarry.models import (
    JobPosting,
    ParsedLocation,
    ParseResult,
    RawPosting,
)
from quarry.pipeline.filter import (
    FILTER_STEPS,
    CompanyFilter,
    KeywordBlocklistFilter,
    LocationFilter,
    cosine_similarity,
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


def _make_raw_posting(**kwargs):
    defaults = dict(
        company_id=1,
        title="Software Engineer",
        url="http://example.com",
        source_type="test",
    )
    defaults.update(kwargs)
    return RawPosting(**defaults)


def _make_posting(**kwargs):
    defaults = dict(
        company_id=1,
        title="Software Engineer",
        title_hash="hash1",
        url="http://example.com",
        source_type="test",
    )
    defaults.update(kwargs)
    return JobPosting(**defaults)


def _make_parse_result(**kwargs):
    defaults = dict(work_model=None, locations=[])
    defaults.update(kwargs)
    return ParseResult(**defaults)


_nyc_loc = ParsedLocation(
    canonical_name="New York, NY",
    city="New York",
    state_code="NY",
    country_code="US",
    region="US-East",
)

_nyc_result = ParseResult(work_model=None, locations=[_nyc_loc])


class TestKeywordBlocklistFilter:
    def test_empty_keywords_passes(self):
        filt = KeywordBlocklistFilter()
        config = KeywordBlocklistConfig()
        raw = _make_raw_posting(title="Senior Eng")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_keyword_match_blocks(self):
        config = KeywordBlocklistConfig(keywords=["staffing agency"])
        filt = KeywordBlocklistFilter()
        raw = _make_raw_posting(title="Staffing Agency Recruiter")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "blocklist"

    def test_passlist_overrides_blocklist(self):
        config = KeywordBlocklistConfig(
            keywords=["senior"], passlist=["senior product"]
        )
        filt = KeywordBlocklistFilter()
        raw = _make_raw_posting(title="Senior Product Manager")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_passlist_no_match_still_blocked(self):
        config = KeywordBlocklistConfig(keywords=["senior"], passlist=["principal"])
        filt = KeywordBlocklistFilter()
        raw = _make_raw_posting(title="Senior Engineer")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "blocklist"

    def test_case_insensitive(self):
        config = KeywordBlocklistConfig(keywords=["STAFFING AGENCY"])
        filt = KeywordBlocklistFilter()
        raw = _make_raw_posting(title="staffing agency recruiter")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is False

    def test_none_config_passes(self):
        filt = KeywordBlocklistFilter()
        config = filt.get_config(None)
        assert config.keywords == []


class TestCompanyFilter:
    def test_empty_allow_and_deny_passes(self):
        config = CompanyFilterConfig()
        filt = CompanyFilter()
        raw = _make_raw_posting()
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_deny_match_blocks(self):
        config = CompanyFilterConfig(deny=["Talentify"])
        filt = CompanyFilter()
        raw = _make_raw_posting()
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Talentify Inc", config)
        assert decision.passed is False
        assert decision.skip_reason == "company_deny"

    def test_deny_no_match_passes(self):
        config = CompanyFilterConfig(deny=["Talentify"])
        filt = CompanyFilter()
        raw = _make_raw_posting()
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_allow_match_passes(self):
        config = CompanyFilterConfig(allow=["Acme Corp"])
        filt = CompanyFilter()
        raw = _make_raw_posting()
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_allow_no_match_blocks(self):
        config = CompanyFilterConfig(allow=["Acme Corp"])
        filt = CompanyFilter()
        raw = _make_raw_posting()
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Other Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "company_allow_skip"

    def test_none_company_name_passes(self):
        config = CompanyFilterConfig(deny=["Talentify"])
        filt = CompanyFilter()
        raw = _make_raw_posting()
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, None, config)
        assert decision.passed is True

    def test_case_insensitive_normalized(self):
        config = CompanyFilterConfig(deny=["talentify"])
        filt = CompanyFilter()
        raw = _make_raw_posting()
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "TALENTIFY Inc.", config)
        assert decision.passed is False


class TestLocationFilter:
    def test_empty_target_location_passes_all(self):
        config = LocationFilterConfig()
        filt = LocationFilter()
        raw = _make_raw_posting(location="New York, NY")
        posting = _make_posting(location="New York, NY")
        decision = filt.check(raw, posting, _nyc_result, "Acme Corp", config)
        assert decision.passed is True

    def test_accept_remote_passes(self):
        config = LocationFilterConfig(
            target_location=["San Francisco"], accept_remote=True
        )
        filt = LocationFilter()
        parse_result = ParseResult(work_model="remote", locations=[])
        raw = _make_raw_posting()
        posting = _make_posting()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_reject_non_remote_when_no_match(self):
        config = LocationFilterConfig(
            target_location=["San Francisco"], accept_remote=False
        )
        filt = LocationFilter()
        raw = _make_raw_posting(location="New York, NY")
        posting = _make_posting(location="New York, NY")
        decision = filt.check(raw, posting, _nyc_result, "Acme Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "location"

    def test_match_via_resolved_city(self):
        config = LocationFilterConfig(target_location=["San Francisco"])
        config.normalize_config()
        filt = LocationFilter()
        parse_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="San Francisco, CA",
                    city="San Francisco",
                    state_code="CA",
                    region="US-West",
                )
            ],
        )
        raw = _make_raw_posting(location="San Francisco, CA")
        posting = _make_posting(location="San Francisco, CA")
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_match_via_accept_states(self):
        config = LocationFilterConfig(
            target_location=["San Francisco"], accept_states=["NY"]
        )
        config.normalize_config()
        filt = LocationFilter()
        raw = _make_raw_posting()
        posting = _make_posting()
        decision = filt.check(raw, posting, _nyc_result, "Acme Corp", config)
        assert decision.passed is True

    def test_match_via_accept_regions(self):
        config = LocationFilterConfig(
            target_location=["Chicago"], accept_regions=["US-West"]
        )
        config.normalize_config()
        filt = LocationFilter()
        parse_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="Portland, OR",
                    city="Portland",
                    state_code="OR",
                    region="US-West",
                )
            ],
        )
        raw = _make_raw_posting()
        posting = _make_posting()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_non_matching_location_rejected(self):
        config = LocationFilterConfig(target_location=["San Francisco"])
        config.normalize_config()
        filt = LocationFilter()
        raw = _make_raw_posting()
        posting = _make_posting()
        decision = filt.check(raw, posting, _nyc_result, "Acme Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "location"

    def test_empty_parse_result_locations_passes(self):
        config = LocationFilterConfig(target_location=["San Francisco"])
        config.normalize_config()
        filt = LocationFilter()
        parse_result = ParseResult(work_model=None, locations=[])
        raw = _make_raw_posting()
        posting = _make_posting()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True


class TestFilterSteps:
    def test_filter_steps_list_exists(self):
        assert len(FILTER_STEPS) == 3
        assert isinstance(FILTER_STEPS[0], KeywordBlocklistFilter)
        assert isinstance(FILTER_STEPS[1], CompanyFilter)
        assert isinstance(FILTER_STEPS[2], LocationFilter)
