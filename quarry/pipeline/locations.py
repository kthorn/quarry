"""Location normalization pipeline: parse, resolve, and canonicalize location strings.

This module handles:
- Splitting compound location strings (pipe, semicolon, or)
- Extracting work model prefixes (Remote, Hybrid, Onsite)
- Resolving city/state/country via geonamescache
- Producing ParsedLocation with canonical names and region assignments
"""

import math
import re
import unicodedata
from functools import lru_cache

import geonamescache

from quarry.models import ParsedLocation, ParseResult

_EARTH_RADIUS_MILES = 3958.8


def haversine_miles(
    lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None
) -> float | None:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    lat1_r, lon1_r, lat2_r, lon2_r = (
        math.radians(lat1),
        math.radians(lon1),
        math.radians(lat2),
        math.radians(lon2),
    )
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return _EARTH_RADIUS_MILES * c


US_STATE_REGIONS = {
    "AK": "US-West",
    "AZ": "US-West",
    "CA": "US-West",
    "CO": "US-West",
    "HI": "US-West",
    "ID": "US-West",
    "MT": "US-West",
    "NM": "US-West",
    "NV": "US-West",
    "OR": "US-West",
    "UT": "US-West",
    "WA": "US-West",
    "WY": "US-West",
    "IA": "US-Central",
    "IL": "US-Central",
    "IN": "US-Central",
    "KS": "US-Central",
    "MI": "US-Central",
    "MN": "US-Central",
    "MO": "US-Central",
    "ND": "US-Central",
    "NE": "US-Central",
    "OH": "US-Central",
    "SD": "US-Central",
    "WI": "US-Central",
    "AL": "US-South",
    "AR": "US-South",
    "DC": "US-South",
    "DE": "US-South",
    "FL": "US-South",
    "GA": "US-South",
    "KY": "US-South",
    "LA": "US-South",
    "MD": "US-South",
    "MS": "US-South",
    "NC": "US-South",
    "OK": "US-South",
    "SC": "US-South",
    "TN": "US-South",
    "TX": "US-South",
    "VA": "US-South",
    "WV": "US-South",
    "CT": "US-East",
    "MA": "US-East",
    "ME": "US-East",
    "NH": "US-East",
    "NJ": "US-East",
    "NY": "US-East",
    "PA": "US-East",
    "RI": "US-East",
    "VT": "US-East",
}

COUNTRY_REGIONS = {
    "AT": "Europe",
    "BE": "Europe",
    "CH": "Europe",
    "CZ": "Europe",
    "DE": "Europe",
    "DK": "Europe",
    "ES": "Europe",
    "FI": "Europe",
    "FR": "Europe",
    "GB": "Europe",
    "GR": "Europe",
    "HR": "Europe",
    "HU": "Europe",
    "IE": "Europe",
    "IT": "Europe",
    "NL": "Europe",
    "NO": "Europe",
    "PL": "Europe",
    "PT": "Europe",
    "RO": "Europe",
    "SE": "Europe",
    "SK": "Europe",
    "UA": "Europe",
    "CN": "Asia",
    "HK": "Asia",
    "IN": "Asia",
    "IL": "Asia",
    "JP": "Asia",
    "KR": "Asia",
    "SG": "Asia",
    "TW": "Asia",
    "TH": "Asia",
    "VN": "Asia",
    "AR": "LATAM",
    "BR": "LATAM",
    "CL": "LATAM",
    "CO": "LATAM",
    "MX": "LATAM",
    "PE": "LATAM",
    "AU": "Oceania",
    "NZ": "Oceania",
    "AE": "Middle East",
    "BH": "Middle East",
    "EG": "Middle East",
    "QA": "Middle East",
    "SA": "Middle East",
    "TR": "Middle East",
    "ZA": "Africa",
    "NG": "Africa",
    "KE": "Africa",
    "MA": "Africa",
    "US": "US-East",
    "CA": "US-West",
}

LOCATION_ALIASES = {
    "IE": "Ireland",
    "CH": "Switzerland",
    "USCA": None,
    "Dublin, IE": "Dublin, Ireland",
    "Ontario, CAN": "Ontario, Canada",
    "San Francisco": "San Francisco, CA",
    "London": "London, United Kingdom",
    "Paris": "Paris, France",
    "Tokyo": "Tokyo, Japan",
    "Singapore": "Singapore",
}

_CITY_ALIASES = {
    "bangalore": "Bengaluru",
    "banglore": "Bengaluru",
    "calcutta": "Kolkata",
    "bombay": "Mumbai",
    "zürich": "Zurich",
    "zurich": "Zurich",
}

_WORK_MODEL_RE = re.compile(
    r"^(remote|hybrid|onsite)\s*[-–—:\s]\s*",
    re.IGNORECASE,
)

_WORK_MODEL_PREFIXES = {"remote", "hybrid", "onsite"}

_WORK_MODEL_PRECEDENCE = {"onsite": 3, "hybrid": 2, "remote": 1}


def _strip_diacritics(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


@lru_cache(maxsize=1)
def _get_gc():
    return geonamescache.GeonamesCache()


def _resolve_us_city(city_name: str, state_code: str | None = None):
    gc = _get_gc()
    candidates = gc.search_cities(
        city_name, case_sensitive=False, contains_search=False
    )
    if not candidates:
        return None
    us_candidates = [c for c in candidates if c["countrycode"] == "US"]
    if not us_candidates:
        return None
    if state_code:
        matched = [c for c in us_candidates if c["admin1code"] == state_code]
        if matched:
            return max(matched, key=lambda c: c["population"])
    return max(us_candidates, key=lambda c: c["population"])


def _resolve_non_us_city(city_name: str, country_code: str | None = None):
    gc = _get_gc()
    candidates = gc.search_cities(
        city_name, case_sensitive=False, contains_search=False
    )
    if not candidates:
        return None
    if country_code:
        filtered = [c for c in candidates if c["countrycode"] == country_code.upper()]
        if filtered:
            return max(filtered, key=lambda c: c["population"])
    return max(candidates, key=lambda c: c["population"])


def _resolve_country(country_name_or_code: str) -> dict | None:
    gc = _get_gc()
    countries = gc.get_countries()
    upper = country_name_or_code.upper()
    if upper in countries:
        return dict(countries[upper])
    for code, info in countries.items():
        if info["name"].lower() == country_name_or_code.lower():
            return dict(info)
    return None


def _find_state_code(state_fragment: str) -> str | None:
    gc = _get_gc()
    states = gc.get_us_states()
    upper = state_fragment.strip().upper()
    if upper in states:
        return upper
    for code, info in states.items():
        if info["name"].lower() == state_fragment.strip().lower():
            return code
    return None


def _get_state_name(states: dict, state_code: str) -> str | None:
    try:
        return states[state_code]["name"]  # type: ignore[index]
    except (KeyError, TypeError):
        return states.get(state_code, {}).get("name")


def split_compound_locations(location: str | None) -> list[str]:
    if not location or not location.strip():
        return []
    location = location.strip()
    for delimiter in (" | ", "; ", " or "):
        if (
            delimiter in location.lower()
            if delimiter == " or "
            else delimiter in location
        ):
            if delimiter == " or ":
                parts = re.split(r"\s+or\s+", location, flags=re.IGNORECASE)
            elif delimiter == "; ":
                parts = location.split("; ")
            else:
                parts = location.split(delimiter)
            return [p.strip() for p in parts if p.strip()]
    return [location]


def extract_work_model(fragments: list[str]) -> tuple[list[str], str | None]:
    if not fragments:
        return [], None

    stripped = []
    models_found = []
    for frag in fragments:
        frag_stripped = frag.strip()
        lower = frag_stripped.lower()

        if lower in _WORK_MODEL_PREFIXES:
            models_found.append(lower)
            continue

        m = _WORK_MODEL_RE.match(frag_stripped)
        if m:
            model = m.group(1).lower()
            remainder = frag_stripped[m.end() :].strip()
            models_found.append(model)
            if remainder:
                stripped.append(remainder)
            continue

        stripped.append(frag_stripped)

    work_model = None
    if models_found:
        work_model = max(models_found, key=lambda m: _WORK_MODEL_PRECEDENCE.get(m, 0))

    return stripped, work_model


def _clean_city_name(name: str) -> str:
    return _strip_diacritics(name)


def _make_us_location(city_result, state_name: str | None = None):
    state_code = city_result["admin1code"]
    region = US_STATE_REGIONS.get(state_code)
    clean_city = _clean_city_name(city_result["name"])
    return ParsedLocation(
        canonical_name=f"{clean_city}, {state_code}",
        city=clean_city,
        state=state_name,
        state_code=state_code,
        country="United States",
        country_code="US",
        region=region,
        latitude=city_result["latitude"],
        longitude=city_result["longitude"],
    )


def _make_non_us_location(city_result, country_code: str):
    countries = _get_gc().get_countries()
    country_name = countries.get(country_code, {}).get("name", country_code)
    region = COUNTRY_REGIONS.get(country_code)
    clean_city = _clean_city_name(city_result["name"])
    return ParsedLocation(
        canonical_name=f"{clean_city}, {country_name}",
        city=clean_city,
        country=country_name,
        country_code=country_code,
        region=region,
        latitude=city_result["latitude"],
        longitude=city_result["longitude"],
    )


def normalize_location_fragment(raw: str) -> ParsedLocation:
    original = raw
    text = raw.strip()

    if text in LOCATION_ALIASES:
        expanded = LOCATION_ALIASES[text]
        if expanded is None:
            return ParsedLocation(
                canonical_name=text,
                resolution_status="needs_review",
                raw_fragment=original,
            )
        text = expanded

    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"\s+", " ", text).strip()

    city_name = None
    state_fragment = None
    country_fragment = None

    parts = [p.strip() for p in text.split(",")]

    if len(parts) == 1:
        city_name = parts[0]
    elif len(parts) == 2:
        city_name = parts[0]
        second = parts[1]
        us_states = _get_gc().get_us_states()
        if second.upper() in us_states or len(second) == 2:
            state_fragment = second
        elif _resolve_country(second):
            country_fragment = second
        else:
            state_fragment = second
    elif len(parts) >= 3:
        city_name = parts[0]
        state_fragment = parts[1]
        country_fragment = parts[2]

    lower_city = city_name.lower() if city_name else ""
    if lower_city in _CITY_ALIASES:
        city_name = _CITY_ALIASES[lower_city]

    gc_states = _get_gc().get_us_states()

    if country_fragment:
        country_info = _resolve_country(country_fragment)
        if not country_info:
            country_code = country_fragment.upper()
        else:
            country_code = country_info["iso"]

        if country_code == "US" and state_fragment:
            state_code = _find_state_code(state_fragment)
            if state_code is None:
                state_code = state_fragment.upper()[:2]
            assert city_name is not None
            city_result = _resolve_us_city(_strip_diacritics(city_name), state_code)
            if city_result:
                state_name = _get_state_name(gc_states, city_result["admin1code"])
                return _make_us_location(city_result, state_name)
            return ParsedLocation(
                canonical_name=f"{city_name}, {state_code}",
                city=city_name,
                state_code=state_code,
                country_code="US",
                country="United States",
                region=US_STATE_REGIONS.get(state_code),
            )

        if city_name:
            search_name = _strip_diacritics(city_name)
            city_result = _resolve_non_us_city(search_name, country_code)
            if city_result:
                return _make_non_us_location(city_result, country_code)
            countries = _get_gc().get_countries()
            country_name = countries.get(country_code, {}).get("name", country_code)
            return ParsedLocation(
                canonical_name=f"{city_name}, {country_name}",
                city=city_name,
                country=country_name,
                country_code=country_code,
                region=COUNTRY_REGIONS.get(country_code),
            )

        countries = _get_gc().get_countries()
        country_name = countries.get(country_code, {}).get("name", country_code)
        return ParsedLocation(
            canonical_name=country_name,
            country=country_name,
            country_code=country_code,
            region=COUNTRY_REGIONS.get(country_code),
        )

    if city_name and not country_fragment:
        if len(parts) == 1 and state_fragment is None:
            country_info = _resolve_country(city_name)
            if country_info:
                cc = country_info["iso"]
                return ParsedLocation(
                    canonical_name=country_info["name"],
                    country=country_info["name"],
                    country_code=cc,
                    region=COUNTRY_REGIONS.get(cc),
                )

            search_name = _strip_diacritics(city_name)
            us_result = _resolve_us_city(search_name)
            if us_result:
                state_name = _get_state_name(gc_states, us_result["admin1code"])
                return _make_us_location(us_result, state_name)

            non_us_result = _resolve_non_us_city(search_name)
            if non_us_result:
                cc = non_us_result["countrycode"]
                return _make_non_us_location(non_us_result, cc)

            return ParsedLocation(
                canonical_name=city_name,
                city=city_name,
                resolution_status="needs_review",
                raw_fragment=original,
            )

        if state_fragment:
            state_code = _find_state_code(state_fragment)
            if state_code is None:
                state_code = state_fragment.upper()[:2]
            city_result = _resolve_us_city(_strip_diacritics(city_name), state_code)
            if city_result:
                state_name = _get_state_name(gc_states, state_code)
                return _make_us_location(city_result, state_name)
            region = US_STATE_REGIONS.get(state_code)
            return ParsedLocation(
                canonical_name=f"{city_name}, {state_code}",
                city=city_name,
                state_code=state_code,
                country="United States",
                country_code="US",
                region=region,
            )

    country_info = _resolve_country(city_name) if city_name else None
    if country_info:
        cc = country_info["iso"]
        return ParsedLocation(
            canonical_name=country_info["name"],
            country=country_info["name"],
            country_code=cc,
            region=COUNTRY_REGIONS.get(cc),
        )

    return ParsedLocation(
        canonical_name=original,
        resolution_status="needs_review",
        raw_fragment=original,
    )


def parse_location(location: str | None) -> ParseResult:
    if location is None or not location.strip():
        return ParseResult(work_model=None, locations=[])

    fragments = split_compound_locations(location)
    fragments, work_model = extract_work_model(fragments)

    locations = []
    for frag in fragments:
        loc = normalize_location_fragment(frag)
        locations.append(loc)

    return ParseResult(work_model=work_model, locations=locations)
