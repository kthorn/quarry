import pytest
from quarry.crawlers.jobspy_client import JobSpyClient


@pytest.fixture
def mock_jobspy_df():
    import pandas as pd

    return pd.DataFrame(
        [
            {
                "title": "Software Engineer",
                "company": "Test Corp",
                "url": "https://example.com/job/1",
                "description": "We are hiring",
                "location": "Remote",
                "date_posted": "2024-01-15",
                "job_type": "full_time",
                "site_name": "Indeed",
            },
        ]
    )


def test_jobspy_client_initialization():
    client = JobSpyClient()
    assert client.sites == [
        "indeed",
        "glassdoor",
        "google",
        "zip_recruiter",
        "linkedin",
    ]
    assert client.results_wanted == 20


def test_jobspy_client_custom_sites():
    client = JobSpyClient(sites=["indeed"])
    assert client.sites == ["indeed"]
