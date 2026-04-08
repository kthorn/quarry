"""Integration tests for extraction pipeline."""

import json
from pathlib import Path

from quarry.models import RawPosting
from quarry.pipeline.extract import extract


def test_extract_with_greenhouse_fixture():
    """Test extraction with real-world Greenhouse posting."""
    fixture_path = Path(__file__).parent / "fixtures" / "greenhouse_posting.json"
    with open(fixture_path) as f:
        data = json.load(f)

    raw = RawPosting(**data)
    result = extract(raw)

    # Check title preserved
    assert result.title == "Senior Software Engineer - Remote"

    # Check HTML stripped
    assert "<div>" not in result.description
    assert "<p>" not in result.description
    assert "Senior Software Engineer" in result.description
    assert "remote position" in result.description

    # Check remote detected
    assert result.remote is True

    # Check location normalized
    assert result.location == "San Francisco, CA, US or Remote"

    # Check title hashed
    assert len(result.title_hash) == 64

    # Check metadata preserved
    assert result.source_id == "12345"
    assert result.source_type == "greenhouse"
