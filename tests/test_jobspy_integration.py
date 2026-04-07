import pytest
from quarry.crawlers.jobspy_client import JobSpyClient


@pytest.mark.skip(
    reason="Integration test - requires network, run manually with -m integration"
)
def test_jobspy_smoke_test():
    """Smoke test - only runs with --runslow or specific marker."""
    client = JobSpyClient(
        sites=["indeed"],
        results_wanted=5,
    )

    postings = client.fetch("software engineer")

    assert isinstance(postings, list)
