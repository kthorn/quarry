from quarry.models import AgentAction, Company, JobPosting, Label
from quarry.store.db import init_db


class TestGetPostingById:
    def test_found(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        posting = JobPosting(
            company_id=cid,
            title="Engineer",
            title_hash="h1",
            url="https://example.com/1",
        )
        pid = db.insert_posting(posting)
        result = db.get_posting_by_id(pid)
        assert result is not None
        assert result.id == pid
        assert result.title == "Engineer"

    def test_not_found(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        result = db.get_posting_by_id(9999)
        assert result is None


class TestUpdatePostingStatus:
    def test_status_update(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        posting = JobPosting(
            company_id=cid,
            title="Engineer",
            title_hash="h2",
            url="https://example.com/2",
            status="new",
        )
        pid = db.insert_posting(posting)
        db.update_posting_status(pid, "applied")
        updated = db.get_posting_by_id(pid)
        assert updated is not None
        assert updated.status == "applied"

    def test_does_not_affect_other_postings(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        p1 = JobPosting(
            company_id=cid,
            title="Engineer A",
            title_hash="h3",
            url="https://example.com/3",
            status="new",
        )
        p2 = JobPosting(
            company_id=cid,
            title="Engineer B",
            title_hash="h4",
            url="https://example.com/4",
            status="new",
        )
        id1 = db.insert_posting(p1)
        id2 = db.insert_posting(p2)
        db.update_posting_status(id1, "applied")
        other = db.get_posting_by_id(id2)
        assert other is not None
        assert other.status == "new"


class TestCountPostings:
    def test_count_all(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        for i in range(3):
            db.insert_posting(
                JobPosting(
                    company_id=cid,
                    title=f"Job {i}",
                    title_hash=f"cnt_{i}",
                    url=f"https://example.com/cnt_{i}",
                )
            )
        assert db.count_postings() == 3

    def test_count_by_status(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            JobPosting(
                company_id=cid,
                title="New Job",
                title_hash="cnt_s1",
                url="https://example.com/cnt_s1",
                status="new",
            )
        )
        db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Seen Job",
                title_hash="cnt_s2",
                url="https://example.com/cnt_s2",
                status="seen",
            )
        )
        assert db.count_postings("new") == 1
        assert db.count_postings("seen") == 1
        assert db.count_postings("applied") == 0

    def test_count_zero_on_empty(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        assert db.count_postings() == 0


class TestGetPostingsPaginated:
    def test_returns_with_company_name(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="AcmeCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Engineer",
                title_hash="pg1",
                url="https://example.com/pg1",
                similarity_score=0.9,
            )
        )
        results = db.get_postings_paginated()
        assert len(results) == 1
        posting, company_name = results[0]
        assert isinstance(posting, JobPosting)
        assert company_name == "AcmeCorp"

    def test_pagination_offset_limit(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        for i in range(5):
            db.insert_posting(
                JobPosting(
                    company_id=cid,
                    title=f"Job {i}",
                    title_hash=f"pgpg_{i}",
                    url=f"https://example.com/pgpg_{i}",
                    similarity_score=float(i),
                )
            )
        page1 = db.get_postings_paginated(limit=2, offset=0)
        assert len(page1) == 2
        page2 = db.get_postings_paginated(limit=2, offset=2)
        assert len(page2) == 2
        page3 = db.get_postings_paginated(limit=2, offset=4)
        assert len(page3) == 1

    def test_sorted_by_similarity_desc(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        for score in [0.3, 0.9, 0.6]:
            db.insert_posting(
                JobPosting(
                    company_id=cid,
                    title=f"Job {score}",
                    title_hash=f"pgsort_{score}",
                    url=f"https://example.com/pgsort_{score}",
                    similarity_score=score,
                )
            )
        results = db.get_postings_paginated()
        scores = [p.similarity_score for p, _ in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_when_no_match(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Job",
                title_hash="pgempty",
                url="https://example.com/pgempty",
                status="new",
            )
        )
        results = db.get_postings_paginated(status="applied")
        assert results == []

    def test_status_filter(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        db.insert_posting(
            JobPosting(
                company_id=cid,
                title="New",
                title_hash="pgst1",
                url="https://example.com/pgst1",
                status="new",
                similarity_score=0.8,
            )
        )
        db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Applied",
                title_hash="pgst2",
                url="https://example.com/pgst2",
                status="applied",
                similarity_score=0.7,
            )
        )
        results = db.get_postings_paginated(status="new")
        assert len(results) == 1
        assert results[0][0].status == "new"

    def test_threshold_filter(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        for i, score in enumerate([0.9, 0.5, 0.2]):
            db.insert_posting(
                JobPosting(
                    company_id=cid,
                    title=f"Job {i}",
                    title_hash=f"pgthr_{i}",
                    url=f"https://example.com/pgthr_{i}",
                    similarity_score=score,
                )
            )
        results = db.get_postings_paginated(threshold=0.5)
        assert len(results) == 2
        for p, _ in results:
            assert p.similarity_score >= 0.5


class TestGetLabelsForPosting:
    def test_returns_labels(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        company = Company(name="TestCorp")
        cid = db.insert_company(company)
        pid = db.insert_posting(
            JobPosting(
                company_id=cid,
                title="Job",
                title_hash="lbl1",
                url="https://example.com/lbl1",
            )
        )
        db.insert_label(Label(posting_id=pid, signal="positive"))
        db.insert_label(Label(posting_id=pid, signal="negative"))
        labels = db.get_labels_for_posting(pid)
        assert len(labels) == 2
        assert labels[0].posting_id == pid

    def test_returns_empty_when_none(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        labels = db.get_labels_for_posting(9999)
        assert labels == []


class TestGetAgentActions:
    def test_returns_actions(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        db.insert_agent_action(
            AgentAction(tool_name="web_search", tool_args='{"q": "test"}')
        )
        db.insert_agent_action(AgentAction(tool_name="summarize", rationale="test"))
        actions = db.get_agent_actions()
        assert len(actions) == 2
        assert actions[0].tool_name in ("web_search", "summarize")

    def test_respects_limit(self, tmp_path):
        db = init_db(tmp_path / "test.db")
        for i in range(10):
            db.insert_agent_action(AgentAction(tool_name=f"tool_{i}"))
        actions = db.get_agent_actions(limit=5)
        assert len(actions) == 5
