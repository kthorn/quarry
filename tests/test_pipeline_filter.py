"""Tests for similarity scoring and filter pipeline."""

import numpy as np
import pytest

from quarry.config import (
    CompanyFilterConfig,
    KeywordBlocklistConfig,
    LocationFilterConfig,
    NoneStrictness,
    TitleKeywordConfig,
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
    TitleKeywordFilter,
    cosine_similarity,
    evaluate_location_match,
    geographic_match,
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


class TestTitleKeywordFilter:
    def test_empty_keywords_passes_all(self):
        config = TitleKeywordConfig()
        filt = TitleKeywordFilter()
        raw = _make_raw_posting(title="Senior Engineer")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_matching_title_passes(self):
        config = TitleKeywordConfig(keywords=["hr", "people"])
        filt = TitleKeywordFilter()
        raw = _make_raw_posting(title="People Analytics Manager")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_non_matching_title_rejected(self):
        config = TitleKeywordConfig(keywords=["hr", "people"])
        filt = TitleKeywordFilter()
        raw = _make_raw_posting(title="Senior Backend Engineer")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is False
        assert decision.skip_reason == "title_keyword"

    def test_case_insensitive(self):
        config = TitleKeywordConfig(keywords=["HR", "People"])
        filt = TitleKeywordFilter()
        raw = _make_raw_posting(title="hr business partner")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_partial_match_in_title(self):
        config = TitleKeywordConfig(keywords=["analytics"])
        filt = TitleKeywordFilter()
        raw = _make_raw_posting(title="Workforce Analytics Lead")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_match_in_description_not_in_title_rejected(self):
        config = TitleKeywordConfig(keywords=["hr", "people"])
        filt = TitleKeywordFilter()
        raw = _make_raw_posting(
            title="Senior Backend Engineer",
            description="Work with the People team on HR systems",
        )
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is False

    def test_any_keyword_match_passes(self):
        config = TitleKeywordConfig(keywords=["hr", "people", "analytics", "workforce"])
        filt = TitleKeywordFilter()
        raw = _make_raw_posting(title="Workforce Planning Director")
        posting = _make_posting()
        parse_result = _make_parse_result()
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_none_config_passes_all(self):
        filt = TitleKeywordFilter()
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
        posting = _make_posting(work_model="remote")
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_accept_remote_with_unknown_work_model_passes(self):
        config = LocationFilterConfig(
            target_location=["San Francisco"], accept_remote=True
        )
        filt = LocationFilter()
        parse_result = ParseResult(work_model=None, locations=[])
        raw = _make_raw_posting()
        posting = _make_posting(work_model=None)
        decision = filt.check(raw, posting, parse_result, "Acme Corp", config)
        assert decision.passed is True

    def test_reject_non_remote_unknown_when_no_match(self):
        config = LocationFilterConfig(
            target_location=["San Francisco"], accept_remote=False
        )
        config.normalize_config()
        filt = LocationFilter()
        raw = _make_raw_posting(location="New York, NY")
        posting = _make_posting(location="New York, NY", work_model="onsite")
        decision = filt.check(raw, posting, _nyc_result, "Acme Corp", config)
        assert decision.passed is False

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
        config = LocationFilterConfig(
            target_location=["San Francisco"], accept_remote=False
        )
        config.normalize_config()
        filt = LocationFilter()
        raw = _make_raw_posting()
        posting = _make_posting(work_model="onsite")
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

    def test_state_match_with_city_does_not_pass(self):
        config = LocationFilterConfig(
            target_location=["San Francisco"], accept_remote=False
        )
        config.normalize_config()
        filt = LocationFilter()
        fresno_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="Fresno, CA",
                    city="Fresno",
                    state_code="CA",
                    region="US-West",
                    latitude=36.7378,
                    longitude=-119.7871,
                )
            ],
        )
        raw = _make_raw_posting()
        posting = _make_posting(work_model="onsite")
        decision = filt.check(raw, posting, fresno_result, "Acme Corp", config)
        assert decision.passed is False

    def test_state_match_without_city_passes(self):
        config = LocationFilterConfig(target_location=[], accept_states=["CA"])
        config.normalize_config()
        filt = LocationFilter()
        ca_state_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="CA",
                    state_code="CA",
                    country="United States",
                    country_code="US",
                    region="US-West",
                )
            ],
        )
        raw = _make_raw_posting()
        posting = _make_posting()
        decision = filt.check(raw, posting, ca_state_result, "Acme Corp", config)
        assert decision.passed is True

    def test_region_match_with_city_does_not_pass(self):
        config = LocationFilterConfig(
            target_location=["San Francisco"], accept_remote=False
        )
        config.normalize_config()
        filt = LocationFilter()
        portland_result = ParseResult(
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
        posting = _make_posting(work_model="onsite")
        decision = filt.check(raw, posting, portland_result, "Acme Corp", config)
        assert decision.passed is False

    def test_region_match_without_city_or_state_passes(self):
        config = LocationFilterConfig(target_location=[], accept_regions=["US-West"])
        config.normalize_config()
        filt = LocationFilter()
        us_west_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="US-West",
                    region="US-West",
                )
            ],
        )
        raw = _make_raw_posting()
        posting = _make_posting()
        decision = filt.check(raw, posting, us_west_result, "Acme Corp", config)
        assert decision.passed is True


class TestLocationFilterHaversine:
    def test_nearby_city_passes_within_radius(self):
        config = LocationFilterConfig(
            target_location=["San Francisco, CA"], nearby_radius=50
        )
        config.normalize_config()
        filt = LocationFilter()
        oakland_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="Oakland, CA",
                    city="Oakland",
                    state_code="CA",
                    region="US-West",
                    latitude=37.8044,
                    longitude=-122.2712,
                )
            ],
        )
        raw = _make_raw_posting()
        posting = _make_posting()
        decision = filt.check(raw, posting, oakland_result, "Acme Corp", config)
        assert decision.passed is True

    def test_distant_city_fails_outside_radius(self):
        config = LocationFilterConfig(
            target_location=["San Francisco, CA"],
            nearby_radius=50,
            accept_remote=False,
        )
        config.normalize_config()
        filt = LocationFilter()
        la_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="Los Angeles, CA",
                    city="Los Angeles",
                    state_code="CA",
                    region="US-West",
                    latitude=34.0522,
                    longitude=-118.2437,
                )
            ],
        )
        raw = _make_raw_posting()
        posting = _make_posting(work_model="onsite")
        decision = filt.check(raw, posting, la_result, "Acme Corp", config)
        assert decision.passed is False

    def test_no_nearby_radius_behaves_as_before(self):
        config = LocationFilterConfig(
            target_location=["San Francisco, CA"], accept_remote=False
        )
        config.normalize_config()
        filt = LocationFilter()
        oakland_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="Oakland, CA",
                    city="Oakland",
                    state_code="CA",
                    region="US-West",
                    latitude=37.8044,
                    longitude=-122.2712,
                )
            ],
        )
        raw = _make_raw_posting()
        posting = _make_posting(work_model="onsite")
        decision = filt.check(raw, posting, oakland_result, "Acme Corp", config)
        assert decision.passed is False

    def test_missing_coordinates_skips_distance_check(self):
        config = LocationFilterConfig(
            target_location=["San Francisco, CA"],
            nearby_radius=50,
            accept_remote=False,
        )
        config.normalize_config()
        filt = LocationFilter()
        unresolved_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="Oakland, CA",
                    city="Oakland",
                    state_code="CA",
                    region="US-West",
                    latitude=None,
                    longitude=None,
                )
            ],
        )
        raw = _make_raw_posting()
        posting = _make_posting(work_model="onsite")
        decision = filt.check(raw, posting, unresolved_result, "Acme Corp", config)
        assert decision.passed is False

    def test_exact_city_match_still_passes_with_radius(self):
        config = LocationFilterConfig(
            target_location=["San Francisco, CA"], nearby_radius=50
        )
        config.normalize_config()
        filt = LocationFilter()
        sf_result = ParseResult(
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
        raw = _make_raw_posting()
        posting = _make_posting()
        decision = filt.check(raw, posting, sf_result, "Acme Corp", config)
        assert decision.passed is True

    def test_nearby_with_zero_radius_ignores_distance(self):
        config = LocationFilterConfig(
            target_location=["San Francisco, CA"],
            nearby_radius=0,
            accept_remote=False,
        )
        config.normalize_config()
        filt = LocationFilter()
        oakland_result = ParseResult(
            work_model=None,
            locations=[
                ParsedLocation(
                    canonical_name="Oakland, CA",
                    city="Oakland",
                    state_code="CA",
                    region="US-West",
                    latitude=37.8044,
                    longitude=-122.2712,
                )
            ],
        )
        raw = _make_raw_posting()
        posting = _make_posting(work_model="onsite")
        decision = filt.check(raw, posting, oakland_result, "Acme Corp", config)
        assert decision.passed is False


class TestFilterSteps:
    def test_filter_steps_list_exists(self):
        assert len(FILTER_STEPS) == 3
        assert isinstance(FILTER_STEPS[0], KeywordBlocklistFilter)
        assert isinstance(FILTER_STEPS[1], TitleKeywordFilter)
        assert isinstance(FILTER_STEPS[2], CompanyFilter)
        # LocationFilter removed from FILTER_STEPS (now at read-time)


# ── evaluate_location_match truth-table tests ─────────────────────


class TestEvaluateLocationMatch:
    """Truth-table tests for the read-time location + work-model filter."""

    def _config(self, **kwargs):
        from quarry.config import LocationFilterConfig

        c = LocationFilterConfig(**kwargs)
        c.normalize_config()
        return c

    def test_filter_off_no_target_no_remote(self):
        config = self._config(target_location=[], accept_remote=False)
        result = evaluate_location_match("San Francisco, CA", "onsite", config)
        assert result.filter_active is False
        assert result.work_type_match is True
        assert result.location_relevant is False
        assert result.location_match is True
        assert result.passes is True

    def test_filter_off_config_none(self):
        result = evaluate_location_match("Anywhere", "onsite", None)
        assert result.filter_active is False
        assert result.work_type_match is True
        assert result.location_relevant is False
        assert result.location_match is True
        assert result.passes is True

    def test_filter_off_none_work_model(self):
        config = self._config(target_location=[], accept_remote=False)
        result = evaluate_location_match("Anywhere", None, config)
        assert result.filter_active is False
        assert result.work_type_match is True
        assert result.location_relevant is False
        assert result.location_match is True
        assert result.passes is True

    def test_onsite_location_matches(self):
        config = self._config(
            target_location=["San Francisco, CA"], accept_remote=False
        )
        result = evaluate_location_match("San Francisco, CA", "onsite", config)
        assert result.filter_active is True
        assert result.work_type_match is True
        assert result.location_relevant is True
        assert result.location_match is True
        assert result.passes is True

    def test_onsite_location_does_not_match(self):
        config = self._config(
            target_location=["San Francisco, CA"], accept_remote=False
        )
        result = evaluate_location_match("New York, NY", "onsite", config)
        assert result.filter_active is True
        assert result.work_type_match is True
        assert result.location_relevant is True
        assert result.location_match is False
        assert result.passes is False

    def test_hybrid_location_matches(self):
        config = self._config(
            target_location=["San Francisco, CA"], accept_remote=False
        )
        result = evaluate_location_match("San Francisco, CA", "hybrid", config)
        assert result.filter_active is True
        assert result.work_type_match is True
        assert result.location_relevant is True
        assert result.location_match is True
        assert result.passes is True

    def test_hybrid_location_does_not_match(self):
        config = self._config(
            target_location=["San Francisco, CA"], accept_remote=False
        )
        result = evaluate_location_match("New York, NY", "hybrid", config)
        assert result.filter_active is True
        assert result.work_type_match is True
        assert result.location_relevant is True
        assert result.location_match is False
        assert result.passes is False

    def test_remote_any_location(self):
        config = self._config(target_location=["San Francisco, CA"], accept_remote=True)
        result = evaluate_location_match("Timbuktu", "remote", config)
        assert result.filter_active is True
        assert result.work_type_match is True
        assert result.location_relevant is False
        assert result.location_match is True
        assert result.passes is True

    def test_remote_accept_remote_false(self):
        config = self._config(
            target_location=["San Francisco, CA"], accept_remote=False
        )
        result = evaluate_location_match("San Francisco, CA", "remote", config)
        assert result.filter_active is True
        assert result.work_type_match is False
        assert result.location_relevant is False
        assert result.location_match is True
        assert result.passes is False

    def test_none_matches_both_strictnesses(self):
        config_g = self._config(
            target_location=["San Francisco, CA"],
            accept_remote=False,
            none_strictness=NoneStrictness.GENEROUS,
        )
        result_g = evaluate_location_match("San Francisco, CA", None, config_g)
        assert result_g.passes is True
        assert result_g.work_type_match is True
        config_s = self._config(
            target_location=["San Francisco, CA"],
            accept_remote=False,
            none_strictness=NoneStrictness.STRICT,
        )
        result_s = evaluate_location_match("San Francisco, CA", None, config_s)
        assert result_s.passes is True
        assert result_s.work_type_match is True

    def test_none_no_match_generous_passes(self):
        config = self._config(
            target_location=["San Francisco, CA"],
            accept_remote=False,
            none_strictness=NoneStrictness.GENEROUS,
        )
        result = evaluate_location_match("New York, NY", None, config)
        assert result.filter_active is True
        assert result.work_type_match is True
        assert result.location_relevant is False  # generous: location ignored
        assert result.passes is True

    def test_none_no_match_strict_fails(self):
        config = self._config(
            target_location=["San Francisco, CA"],
            accept_remote=False,
            none_strictness=NoneStrictness.STRICT,
        )
        result = evaluate_location_match("New York, NY", None, config)
        assert result.filter_active is True
        assert result.work_type_match is True  # strict: targets_set=True
        assert result.passes is False

    def test_none_unparseable_generous_passes(self):
        config = self._config(
            target_location=["San Francisco, CA"],
            accept_remote=False,
            none_strictness=NoneStrictness.GENEROUS,
        )
        result = evaluate_location_match("asdf qwerty zxcv", None, config)
        assert result.filter_active is True
        assert result.work_type_match is True
        assert result.location_relevant is False  # generous: location ignored
        assert result.passes is True

    def test_none_unparseable_strict_fails(self):
        config = self._config(
            target_location=["San Francisco, CA"],
            accept_remote=False,
            none_strictness=NoneStrictness.STRICT,
        )
        result = evaluate_location_match("asdf qwerty zxcv", None, config)
        assert result.filter_active is True
        assert (
            result.work_type_match is True
        )  # strict: targets_set=True -> treat like in-person
        assert result.location_relevant is True
        assert result.passes is False

    def test_remote_only_prefs_onsite_fails(self):
        config = self._config(target_location=[], accept_remote=True)
        result = evaluate_location_match("San Francisco, CA", "onsite", config)
        assert result.filter_active is True
        assert result.work_type_match is False
        assert result.location_relevant is False
        assert result.location_match is True
        assert result.passes is False

    def test_remote_only_prefs_none_generous_passes(self):
        config = self._config(
            target_location=[],
            accept_remote=True,
            none_strictness=NoneStrictness.GENEROUS,
        )
        result = evaluate_location_match("Anywhere", None, config)
        assert result.filter_active is True
        assert result.work_type_match is True
        assert result.passes is True

    def test_does_not_mutate_config(self):
        config = self._config(
            target_location=["San Francisco, CA"],
            accept_states=["NY"],
            accept_regions=["US-West"],
        )
        cities_before = set(config._resolved_cities)
        states_before = set(config._resolved_states)
        regions_before = set(config._resolved_regions)
        coords_before = list(config._resolved_target_coords)
        states_accept_before = set(config._resolved_states_from_accept)
        regions_accept_before = set(config._resolved_regions_from_accept)
        evaluate_location_match("New York, NY", "onsite", config)
        evaluate_location_match("San Francisco, CA", "hybrid", config)
        evaluate_location_match("Remote", "remote", config)
        assert set(config._resolved_cities) == cities_before
        assert set(config._resolved_states) == states_before
        assert set(config._resolved_regions) == regions_before
        assert list(config._resolved_target_coords) == coords_before
        assert set(config._resolved_states_from_accept) == states_accept_before
        assert set(config._resolved_regions_from_accept) == regions_accept_before


# ── geographic_match unit tests ────────────────────────────────────


class TestGeographicMatch:
    def _config(self, **kwargs):
        from quarry.config import LocationFilterConfig

        c = LocationFilterConfig(**kwargs)
        c.normalize_config()
        return c

    def test_city_match(self):
        config = self._config(target_location=["San Francisco, CA"])
        sf_loc = ParsedLocation(
            canonical_name="San Francisco, CA",
            city="San Francisco",
            state_code="CA",
            region="US-West",
        )
        pr = ParseResult(work_model=None, locations=[sf_loc])
        assert geographic_match(pr, config) is True

    def test_nearby_radius_match(self):
        config = self._config(target_location=["San Francisco, CA"], nearby_radius=50)
        oakland = ParsedLocation(
            canonical_name="Oakland, CA",
            city="Oakland",
            state_code="CA",
            region="US-West",
            latitude=37.8044,
            longitude=-122.2712,
        )
        pr = ParseResult(work_model=None, locations=[oakland])
        assert geographic_match(pr, config) is True

    def test_state_match(self):
        config = self._config(accept_states=["NY"])
        ny_loc = ParsedLocation(
            canonical_name="New York, NY",
            city="New York",
            state_code="NY",
            region="US-East",
        )
        pr = ParseResult(work_model=None, locations=[ny_loc])
        assert geographic_match(pr, config) is True

    def test_region_match(self):
        config = self._config(accept_regions=["US-West"])
        portland = ParsedLocation(
            canonical_name="Portland, OR",
            city=None,
            state_code="OR",
            region="US-West",
        )
        pr = ParseResult(work_model=None, locations=[portland])
        assert geographic_match(pr, config) is True

    def test_no_match(self):
        config = self._config(
            target_location=["San Francisco, CA"], accept_remote=False
        )
        ny_loc = ParsedLocation(
            canonical_name="New York, NY",
            city="New York",
            state_code="NY",
            region="US-East",
        )
        pr = ParseResult(work_model=None, locations=[ny_loc])
        assert geographic_match(pr, config) is False
