from quarry.crawlers.jobspy_client import JobSpyClient


def test_jobspy_smoke_test():
    """Smoke test - only runs with --runslow or specific marker."""
    client = JobSpyClient(
        sites=["indeed"],
        results_wanted=5,
    )

    postings = client.fetch("software engineer")

    assert isinstance(postings, list)
