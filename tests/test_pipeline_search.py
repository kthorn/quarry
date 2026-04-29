"""Tests for the search CLI module."""

import numpy as np

from quarry.models import JobPosting
from quarry.pipeline.search import (
    filter_by_keywords,
    format_results,
    match_keywords,
    score_postings,
)


def _make_posting(
    title: str = "Software Engineer",
    description: str | None = "Build things with Python",
    embedding: bytes | None = None,
) -> JobPosting:
    return JobPosting(
        id=1,
        company_id=1,
        title=title,
        title_hash="hash",
        url="https://example.com",
        description=description,
        location="Remote",
        similarity_score=0.8,
        embedding=embedding,
    )


class TestMatchKeywords:
    def test_simple_match(self):
        assert match_keywords("Senior Python Developer", ["python"]) == ["python"]

    def test_case_insensitive(self):
        assert match_keywords("Senior PYTHON Developer", ["python"]) == ["python"]

    def test_whole_word_only(self):
        result = match_keywords("pythonic code style", ["python"])
        assert result == []

    def test_whole_word_match(self):
        result = match_keywords("I love python", ["python"])
        assert result == ["python"]

    def test_multiple_keywords_any_match(self):
        result = match_keywords("Senior Developer", ["python", "senior"])
        assert "senior" in result
        assert "python" not in result

    def test_no_match(self):
        assert match_keywords("Junior Designer", ["python", "aws"]) == []

    def test_empty_keywords(self):
        assert match_keywords("anything", []) == []

    def test_empty_text(self):
        assert match_keywords("", ["python"]) == []

    def test_special_regex_chars(self):
        result = match_keywords("C++ Developer needed", ["c++"])
        assert result == ["c++"]


class TestFilterByKeywords:
    def _make_tuples(self, postings_with_companies):
        return [
            (_make_posting(title=title, description=desc), company)
            for title, desc, company in postings_with_companies
        ]

    def test_title_filter_any_match(self):
        data = self._make_tuples(
            [
                ("Senior Python Dev", "Build things", "Acme"),
                ("Junior Designer", "Design UI", "Beta"),
            ]
        )
        result = filter_by_keywords(data, must_have_title=["senior"])
        assert len(result) == 1
        assert result[0][0].title == "Senior Python Dev"

    def test_description_filter_any_match(self):
        data = self._make_tuples(
            [
                ("Dev", "Python backend with AWS", "Acme"),
                ("Dev", "Frontend React specialist", "Beta"),
            ]
        )
        result = filter_by_keywords(data, must_have_description=["python"])
        assert len(result) == 1
        assert "python" in result[0][3]

    def test_both_filters_and_logic(self):
        data = self._make_tuples(
            [
                ("Senior Dev", "Python backend", "Acme"),
                ("Junior Dev", "Python backend", "Beta"),
                ("Senior Dev", "Frontend React", "Gamma"),
            ]
        )
        result = filter_by_keywords(
            data, must_have_title=["senior"], must_have_description=["python"]
        )
        assert len(result) == 1
        assert result[0][0].title == "Senior Dev"

    def test_no_filters_returns_all(self):
        data = self._make_tuples(
            [
                ("Dev", "Python backend", "Acme"),
                ("Designer", "UI work", "Beta"),
            ]
        )
        result = filter_by_keywords(data)
        assert len(result) == 2

    def test_title_or_within_list(self):
        data = self._make_tuples(
            [
                ("Senior Dev", "Python", "Acme"),
                ("Lead Dev", "Python", "Beta"),
                ("Junior Dev", "Python", "Gamma"),
            ]
        )
        result = filter_by_keywords(data, must_have_title=["senior", "lead"])
        assert len(result) == 2


class TestScorePostings:
    def test_scores_and_sorts(self):
        dim = 8
        ideal = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        close = np.array([0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32)
        far = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0], dtype=np.float32)

        postings = [
            (
                _make_posting(
                    title="Far Job",
                    embedding=far.tobytes(),
                ),
                "FarCo",
                [],
                [],
            ),
            (
                _make_posting(
                    title="Close Job",
                    embedding=close.tobytes(),
                ),
                "CloseCo",
                [],
                [],
            ),
        ]

        results = score_postings(postings, ideal, dim)
        assert len(results) == 2
        assert results[0]["title"] == "Close Job"
        assert results[0]["score"] > results[1]["score"]

    def test_skips_postings_without_embedding(self):
        dim = 8
        ideal = np.zeros(dim, dtype=np.float32)
        postings = [
            (
                _make_posting(embedding=None),
                "Co",
                [],
                [],
            ),
        ]
        results = score_postings(postings, ideal, dim)
        assert len(results) == 0


class TestFormatResults:
    def test_no_results(self):
        output = format_results(
            [],
            has_score=False,
            has_title_keywords=False,
            has_desc_keywords=False,
            limit=10,
        )
        assert "No results found" in output

    def test_basic_format(self):
        results = [
            {
                "title": "Senior Dev",
                "company": "Acme",
                "score": 0.85,
                "matched_title": ["senior"],
                "matched_desc": ["python"],
            }
        ]
        output = format_results(
            results,
            has_score=True,
            has_title_keywords=True,
            has_desc_keywords=True,
            limit=10,
        )
        assert "Senior Dev" in output
        assert "Acme" in output
        assert "Showing 1 result" in output

    def test_min_score_filter(self):
        results = [
            {
                "title": "Low",
                "company": "A",
                "score": 0.2,
                "matched_title": [],
                "matched_desc": [],
            },
            {
                "title": "High",
                "company": "B",
                "score": 0.9,
                "matched_title": [],
                "matched_desc": [],
            },
        ]
        output = format_results(
            results,
            has_score=True,
            has_title_keywords=False,
            has_desc_keywords=False,
            limit=10,
            min_score=0.5,
        )
        assert "High" in output
        assert "Low" not in output

    def test_limit_applied(self):
        results = [
            {
                "title": f"Job {i}",
                "company": "Co",
                "score": 0.5,
                "matched_title": [],
                "matched_desc": [],
            }
            for i in range(50)
        ]
        output = format_results(
            results,
            has_score=True,
            has_title_keywords=False,
            has_desc_keywords=False,
            limit=5,
        )
        assert "Showing 5 result" in output
