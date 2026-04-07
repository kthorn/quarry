from quarry.config import Settings


def test_crawler_config_defaults():
    settings = Settings()
    assert settings.jobspy_sites == [
        "indeed",
        "glassdoor",
        "google",
        "zip_recruiter",
        "linkedin",
    ]
    assert settings.jobspy_results_wanted == 20
    assert settings.jobspy_hours_old == 168
    assert settings.max_retries == 3
    assert settings.retry_base_delay == 2
    assert settings.max_concurrent_per_host == 3
    assert settings.request_timeout == 10
    assert settings.max_response_bytes == 1048576
    assert settings.max_redirects == 5
