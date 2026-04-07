from quarry.models import Company, JobPosting, RawPosting


def test_company_defaults():
    company = Company(name="Test Corp")
    assert company.name == "Test Corp"
    assert company.ats_type == "unknown"
    assert company.active is True


def test_raw_posting_required_fields():
    posting = RawPosting(
        company_id=1,
        title="Software Engineer",
        url="https://example.com/job",
        source_type="greenhouse",
    )
    assert posting.title == "Software Engineer"


def test_job_posting_status_default():
    posting = JobPosting(
        company_id=1,
        title="Engineer",
        url="https://example.com",
        title_hash="abc",
        status="new",
    )
    assert posting.status == "new"
