from quarry.models import Company
from quarry.store.db import init_db


def test_full_resolve_pipeline_e2e(tmp_path):
    db = init_db(tmp_path / "test_e2e.db")

    company = Company(name="Greenhouse Test Corp")
    company.id = db.insert_company(company)
    assert company.id is not None

    fetched = db.get_company(company.id)
    assert fetched is not None
    assert fetched.resolve_status == "unresolved"
    assert fetched.resolve_attempts == 0

    company.domain = "example.com"
    company.careers_url = "https://boards.greenhouse.io/examplecorp"
    company.ats_type = "greenhouse"
    company.ats_slug = "examplecorp"
    company.resolve_status = "resolved"
    db.update_company(company)

    fetched = db.get_company(company.id)
    assert fetched.resolve_status == "resolved"
    assert fetched.ats_type == "greenhouse"
