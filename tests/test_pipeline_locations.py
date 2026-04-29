"""Tests for location parsing module."""

import pytest

from quarry.pipeline.locations import (
    extract_work_model,
    haversine_miles,
    normalize_location_fragment,
    parse_location,
    split_compound_locations,
)


class TestHaversineMiles:
    def test_same_point_returns_zero(self):
        assert haversine_miles(37.7749, -122.4194, 37.7749, -122.4194) == pytest.approx(
            0.0, abs=0.01
        )

    def test_sf_to_oakland(self):
        distance = haversine_miles(37.7749, -122.4194, 37.8044, -122.2712)
        assert 5 < distance < 15

    def test_sf_to_la(self):
        distance = haversine_miles(37.7749, -122.4194, 34.0522, -118.2437)
        assert 340 < distance < 360

    def test_none_lat1_returns_none(self):
        assert haversine_miles(None, -122.4194, 37.8044, -122.2712) is None

    def test_none_lon1_returns_none(self):
        assert haversine_miles(37.7749, None, 37.8044, -122.2712) is None

    def test_none_lat2_returns_none(self):
        assert haversine_miles(37.7749, -122.4194, None, -122.2712) is None

    def test_none_lon2_returns_none(self):
        assert haversine_miles(37.7749, -122.4194, 37.8044, None) is None

    def test_symmetric(self):
        d1 = haversine_miles(37.7749, -122.4194, 34.0522, -118.2437)
        d2 = haversine_miles(34.0522, -118.2437, 37.7749, -122.4194)
        assert d1 == pytest.approx(d2, abs=0.01)


class TestSplitCompoundLocations:
    def test_pipe_delimiter(self):
        assert split_compound_locations("San Francisco, CA | New York City, NY") == [
            "San Francisco, CA",
            "New York City, NY",
        ]

    def test_semicolon_delimiter(self):
        assert split_compound_locations("Berlin, Germany; Munich, Germany") == [
            "Berlin, Germany",
            "Munich, Germany",
        ]

    def test_or_delimiter(self):
        assert split_compound_locations("San Francisco, CA, USA or Remote") == [
            "San Francisco, CA, USA",
            "Remote",
        ]

    def test_single_location(self):
        assert split_compound_locations("San Francisco, CA") == ["San Francisco, CA"]

    def test_empty_string(self):
        assert split_compound_locations("") == []

    def test_none(self):
        assert split_compound_locations(None) == []

    def test_whitespace_only(self):
        assert split_compound_locations("   ") == []

    def test_pipe_delimiter_variations(self):
        assert split_compound_locations("A | B | C") == ["A", "B", "C"]


class TestExtractWorkModel:
    def test_remote_prefix_hyphen(self):
        fragments, work_model = extract_work_model(["Hybrid- Fremont, CA"])
        assert work_model == "hybrid"
        assert fragments == ["Fremont, CA"]

    def test_remote_prefix_space(self):
        fragments, work_model = extract_work_model(["Remote - California"])
        assert work_model == "remote"
        assert fragments == ["California"]

    def test_onsite_prefix(self):
        fragments, work_model = extract_work_model(["Onsite- Pittsburgh, PA"])
        assert work_model == "onsite"
        assert fragments == ["Pittsburgh, PA"]

    def test_pure_remote(self):
        fragments, work_model = extract_work_model(["Remote"])
        assert work_model == "remote"
        assert fragments == []

    def test_no_prefix(self):
        fragments, work_model = extract_work_model(["San Francisco, CA"])
        assert work_model is None
        assert fragments == ["San Francisco, CA"]

    def test_mixed_prefixes_most_specific_wins(self):
        fragments, work_model = extract_work_model(["Hybrid- SF", "Onsite- NYC"])
        assert work_model == "onsite"
        assert fragments == ["SF", "NYC"]

    def test_case_insensitive(self):
        fragments, work_model = extract_work_model(["REMOTE - US"])
        assert work_model == "remote"
        assert fragments == ["US"]

    def test_empty_input(self):
        fragments, work_model = extract_work_model([])
        assert work_model is None
        assert fragments == []


class TestNormalizeLocationFragment:
    def test_us_city_with_state_code(self):
        result = normalize_location_fragment("San Francisco, CA")
        assert result.canonical_name == "San Francisco, CA"
        assert result.city == "San Francisco"
        assert result.state_code == "CA"
        assert result.country_code == "US"

    def test_us_city_without_state(self):
        result = normalize_location_fragment("San Francisco")
        assert result.canonical_name == "San Francisco, CA"
        assert result.city == "San Francisco"

    def test_country_only(self):
        result = normalize_location_fragment("United States")
        assert result.canonical_name == "United States"
        assert result.country_code == "US"
        assert result.city is None

    def test_alias_expansion(self):
        result = normalize_location_fragment("IE")
        assert result.canonical_name == "Ireland"
        assert result.country_code == "IE"

    def test_flagged_unknown(self):
        result = normalize_location_fragment("USCA")
        assert result.resolution_status == "needs_review"

    def test_city_diacritics(self):
        result = normalize_location_fragment("Zürich, Switzerland")
        assert result.city == "Zurich"
        assert result.country_code == "CH"


class TestParseLocation:
    def test_simple_city_state(self):
        result = parse_location("San Francisco, CA")
        assert result.work_model is None
        assert len(result.locations) >= 1
        assert result.locations[0].city == "San Francisco"

    def test_remote_only(self):
        result = parse_location("Remote")
        assert result.work_model == "remote"
        assert result.locations == []

    def test_compound_with_pipe(self):
        result = parse_location("San Francisco, CA | New York City, NY")
        assert len(result.locations) >= 2

    def test_remote_prefix(self):
        result = parse_location("Remote - California")
        assert result.work_model == "remote"
        assert len(result.locations) >= 1

    def test_hybrid_prefix(self):
        result = parse_location("Hybrid- Fremont, CA")
        assert result.work_model == "hybrid"
        assert len(result.locations) >= 1

    def test_none_location(self):
        result = parse_location(None)
        assert result.work_model is None
        assert result.locations == []

    def test_empty_location(self):
        result = parse_location("")
        assert result.work_model is None
        assert result.locations == []
