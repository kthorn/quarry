# M4: Embedding & Similarity Filter — Implementation Plan

**Status:** Refined

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embed job postings and score them against an ideal role description using cosine similarity, then filter out blocklisted keywords and below-threshold results.

**Architecture:** Use `sentence-transformers` with `all-MiniLM-L6-v2` to embed text locally (no API cost). The embedder is a singleton that loads the model once. A `score_similarity()` function computes cosine similarity between a posting embedding and a cached ideal-role embedding stored in the `settings` DB table. A keyword blocklist filter rejects postings containing blocked phrases. The `pipeline/filter.py` orchestrates: extract → embed → score → blocklist check → return `FilterResult`.

**Tech Stack:** sentence-transformers, numpy, quarry.store.db (SQLite), quarry.config (Settings), quarry.models (JobPosting, RawPosting, FilterResult)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `quarry/pipeline/embedder.py` | Model loading, text → embedding, ideal-role caching |
| `quarry/pipeline/filter.py` | Similarity scoring, blocklist filter, full filter pipeline |
| `tests/test_pipeline_embedder.py` | Unit + integration tests for embedder |
| `tests/test_pipeline_filter.py` | Unit tests for similarity, blocklist, filter pipeline |

No changes to `quarry/models.py` — `FilterResult` and `JobPosting.similarity_score` / `JobPosting.embedding` already exist. No changes to `quarry/store/schema.py` — `settings` table and `embedding` BLOB column already exist. No changes to `quarry/store/db.py` — `get_setting()` / `set_setting()` already exist.

---

### Task 1: Embedder — model loading and text embedding

**Files:**
- Create: `quarry/pipeline/embedder.py`
- Test: `tests/test_pipeline_embedder.py`

- [ ] **Step 1: Write tests for embedder**

Create `tests/test_pipeline_embedder.py`:

```python
"""Tests for embedding pipeline."""

import numpy as np
import pytest

from quarry.pipeline.embedder import (
    embed_text,
    embed_posting,
    get_embedding_dim,
    get_ideal_embedding,
    set_ideal_embedding,
)


class TestEmbedText:
    def test_returns_ndarray(self):
        result = embed_text("Senior software engineer")
        assert isinstance(result, np.ndarray)

    def test_dimension(self):
        result = embed_text("Senior software engineer")
        assert result.shape == (get_embedding_dim(),)

    def test_normalized(self):
        result = embed_text("Senior software engineer")
        norm = np.linalg.norm(result)
        assert abs(norm - 1.0) < 1e-6

    def test_different_text_differs(self):
        r1 = embed_text("Senior software engineer")
        r2 = embed_text("Head chef at a restaurant")
        cos = np.dot(r1, r2) / (np.linalg.norm(r1) * np.linalg.norm(r2))
        assert cos < 0.9

    def test_similar_text_close(self):
        r1 = embed_text("Senior people analytics leader")
        r2 = embed_text("Director of HR technology")
        cos = np.dot(r1, r2) / (np.linalg.norm(r1) * np.linalg.norm(r2))
        assert cos > 0.3

    def test_empty_string_returns_zeros(self):
        result = embed_text("")
        assert isinstance(result, np.ndarray)
        assert np.allclose(result, np.zeros_like(result))

    def test_deterministic(self):
        r1 = embed_text("Software engineer")
        r2 = embed_text("Software engineer")
        assert np.allclose(r1, r2)


class TestEmbedPosting:
    def test_combines_title_and_description(self):
        from quarry.models import RawPosting

        raw = RawPosting(
            company_id=1,
            title="Senior Data Scientist",
            url="https://example.com/1",
            description="Build ML models for workforce analytics",
            location="Remote",
            source_type="greenhouse",
        )
        result = embed_posting(raw)
        assert isinstance(result, np.ndarray)
        assert result.shape == (get_embedding_dim(),)

    def test_title_only_when_no_description(self):
        from quarry.models import RawPosting

        raw = RawPosting(
            company_id=1,
            title="Software Engineer",
            url="https://example.com/2",
            source_type="lever",
        )
        result = embed_posting(raw)
        assert isinstance(result, np.ndarray)
        assert result.shape == (get_embedding_dim(),)


class TestIdealEmbedding:
    def test_set_and_get(self, tmp_path):
        from quarry.store.db import init_db

        db = init_db(str(tmp_path / "test.db"))
        desc = "Senior people analytics leader at a tech company"
        set_ideal_embedding(db, desc)

        result = get_ideal_embedding(db)
        assert result is not None
        assert isinstance(result, np.ndarray)
        assert result.shape == (get_embedding_dim(),)

    def test_get_returns_none_when_not_set(self, tmp_path):
        from quarry.store.db import init_db

        db = init_db(str(tmp_path / "test2.db"))
        result = get_ideal_embedding(db)
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_pipeline_embedder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.pipeline.embedder'`

- [ ] **Step 3: Implement embedder module**

Create `quarry/pipeline/embedder.py`:

```python
"""Embedding pipeline: text and postings → vector embeddings.

Uses sentence-transformers (default: all-MiniLM-L6-v2) for local embedding.
Stores the ideal role embedding in the settings DB table for reuse.
"""

import logging

import numpy as np

from quarry.models import RawPosting

log = logging.getLogger(__name__)

_model = None


def _get_model():
    """Load the sentence-transformers model (cached singleton).

    Uses a module-level variable instead of lru_cache so the model
    can be garbage-collected and reloaded if the config changes.
    """
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        model_name = _get_model_name()
        log.info("Loading embedding model: %s", model_name)
        _model = SentenceTransformer(model_name)
    return _model


def _get_model_name() -> str:
    """Get the configured embedding model name."""
    from quarry.config import settings

    return settings.embedding_model


def _get_embedding_dim() -> int:
    """Get the output dimension of the current model.

    Queries sentence-transformers for the model's embedding dimension
    rather than hardcoding 384, so switching models (e.g. to all-mpnet-base-v2)
    works correctly.
    """
    model = _get_model()
    return model.get_sentence_embedding_dimension()


def embed_text(text: str) -> np.ndarray:
    """Embed a single text string into a vector.

    Args:
        text: Text to embed. Empty string returns zero vector.

    Returns:
        Normalized numpy array whose dimension matches the configured model.
    """
    if not text or not text.strip():
        dim = _get_embedding_dim()
        return np.zeros(dim, dtype=np.float32)

    model = _get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.astype(np.float32)


def embed_posting(posting: RawPosting) -> np.ndarray:
    """Embed a job posting by combining title, description, and location.

    Concatenates title + description + location into a single text
    for embedding, which captures the full context.

    Args:
        posting: RawPosting to embed.

    Returns:
        Normalized numpy array embedding.
    """
    parts = [posting.title]
    if posting.description:
        parts.append(posting.description)
    if posting.location:
        parts.append(posting.location)
    text = " ".join(parts)
    return embed_text(text)


def get_embedding_dim() -> int:
    """Get the output dimension of the configured embedding model.

    Useful for downstream code that needs to know vector size
    without calling embed_text first.
    """
    return _get_embedding_dim()


def serialize_embedding(embedding: np.ndarray) -> bytes:
    """Serialize numpy embedding to bytes for DB storage.

    Args:
        embedding: numpy array to serialize.

    Returns:
        Bytes representation.
    """
    return embedding.tobytes()


def deserialize_embedding(data: bytes, dim: int | None = None) -> np.ndarray:
    """Deserialize embedding from DB bytes.

    Args:
        data: Bytes from DB BLOB column.
        dim: Expected embedding dimension. If provided, validates the
             deserialized array has the correct length.

    Returns:
        numpy array of shape (dim,).

    Raises:
        ValueError: If dim is provided and data length doesn't match.
    """
    arr = np.frombuffer(data, dtype=np.float32)
    if dim is not None and arr.shape[0] != dim:
        raise ValueError(
            f"Embedding dimension mismatch: expected {dim}, got {arr.shape[0]}"
        )
    return arr


def set_ideal_embedding(db, description: str) -> np.ndarray:
    """Compute and store the ideal role embedding in DB settings.

    Args:
        db: Database instance.
        description: The ideal role description text.

    Returns:
        The computed embedding vector.
    """
    embedding = embed_text(description)
    db.set_setting("ideal_role_embedding", serialize_embedding(embedding).hex())
    db.set_setting("ideal_role_description", description)
    return embedding


def get_ideal_embedding(db) -> np.ndarray | None:
    """Retrieve the stored ideal role embedding from DB.

    Args:
        db: Database instance.

    Returns:
        Stored embedding vector, or None if not set.
    """
    hex_str = db.get_setting("ideal_role_embedding")
    if hex_str is None:
        return None
    raw = bytes.fromhex(hex_str)
    return deserialize_embedding(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_pipeline_embedder.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/pipeline/embedder.py tests/test_pipeline_embedder.py
git commit -m "feat: add embedding module with sentence-transformers"
```

---

### Task 2: Similarity scoring and keyword blocklist

**Files:**
- Create: `quarry/pipeline/filter.py`
- Test: `tests/test_pipeline_filter.py`

- [ ] **Step 1: Write tests for filter module**

Create `tests/test_pipeline_filter.py`:

```python
"""Tests for similarity filter and keyword blocklist."""

import numpy as np
import pytest

from quarry.models import FilterResult, JobPosting, RawPosting
from quarry.pipeline.filter import (
    apply_keyword_blocklist,
    cosine_similarity,
    score_similarity,
    filter_posting,
)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = np.array([1.0, 0.0, 0.0])
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        v1 = np.array([1.0, 0.0, 0.0])
        v2 = np.array([0.0, 1.0, 0.0])
        assert cosine_similarity(v1, v2) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        v1 = np.array([1.0, 0.0])
        v2 = np.array([-1.0, 0.0])
        assert cosine_similarity(v1, v2) == pytest.approx(-1.0)

    def test_similarity_range(self):
        v1 = np.random.rand(384)
        v2 = np.random.rand(384)
        sim = cosine_similarity(v1, v2)
        assert -1.0 <= sim <= 1.0

    def test_zero_vector_returns_zero(self):
        v1 = np.zeros(384)
        v2 = np.random.rand(384)
        assert cosine_similarity(v1, v2) == 0.0


class TestScoreSimilarity:
    def test_relevant_posting_high_score(self):
        ideal = np.random.rand(384).astype(np.float32)
        ideal = ideal / np.linalg.norm(ideal)
        posting_emb = ideal * 0.95 + np.random.rand(384) * 0.05
        posting_emb = posting_emb / np.linalg.norm(posting_emb)

        score = score_similarity(posting_emb, ideal)
        assert score > 0.9

    def test_irrelevant_posting_low_score(self):
        ideal = np.zeros(384, dtype=np.float32)
        ideal[0] = 1.0

        irrelevant = np.zeros(384, dtype=np.float32)
        irrelevant[100] = 1.0

        score = score_similarity(irrelevant, ideal)
        assert score < 0.2

    def test_identical_vectors_score_one(self):
        v = np.random.rand(384).astype(np.float32)
        v = v / np.linalg.norm(v)
        assert score_similarity(v, v) == pytest.approx(1.0, abs=1e-5)


class TestApplyKeywordBlocklist:
    def test_blocklisted_keyword_in_title(self):
        posting = RawPosting(
            company_id=1,
            title="Staffing Agency Recruiter",
            url="https://example.com/1",
            source_type="greenhouse",
        )
        blocklist = ["staffing agency"]
        assert apply_keyword_blocklist(posting, blocklist) is False

    def test_blocklisted_keyword_in_description(self):
        posting = RawPosting(
            company_id=1,
            title="Engineer",
            url="https://example.com/2",
            description="This role requires clearance",
            source_type="greenhouse",
        )
        blocklist = ["requires clearance"]
        assert apply_keyword_blocklist(posting, blocklist) is False

    def test_no_blocklist_match(self):
        posting = RawPosting(
            company_id=1,
            title="Senior Engineer",
            url="https://example.com/3",
            description="Build great products",
            source_type="greenhouse",
        )
        blocklist = ["staffing agency", "relocation required"]
        assert apply_keyword_blocklist(posting, blocklist) is True

    def test_case_insensitive_match(self):
        posting = RawPosting(
            company_id=1,
            title="STAFFING AGENCY recruiter",
            url="https://example.com/4",
            source_type="lever",
        )
        blocklist = ["staffing agency"]
        assert apply_keyword_blocklist(posting, blocklist) is False

    def test_empty_blocklist_passes(self):
        posting = RawPosting(
            company_id=1,
            title="Anything goes",
            url="https://example.com/5",
            source_type="greenhouse",
        )
        assert apply_keyword_blocklist(posting, []) is True

    def test_partial_match_is_not_blocked(self):
        posting = RawPosting(
            company_id=1,
            title="Remote staffing coordinator",
            url="https://example.com/6",
            description="Internal team, not an agency",
            source_type="greenhouse",
        )
        blocklist = ["staffing agency"]
        assert apply_keyword_blocklist(posting, blocklist) is True

    def test_blocklisted_in_location(self):
        posting = RawPosting(
            company_id=1,
            title="Engineer",
            url="https://example.com/7",
            location="Relocation required - San Francisco",
            source_type="greenhouse",
        )
        blocklist = ["relocation required"]
        assert apply_keyword_blocklist(posting, blocklist) is False


class TestFilterPosting:
    def test_passes_relevant_posting(self):
        from unittest.mock import patch

        raw = RawPosting(
            company_id=1,
            title="Senior People Analytics Manager",
            url="https://example.com/1",
            description="Lead analytics team",
            source_type="greenhouse",
        )
        ideal_emb = np.random.rand(384).astype(np.float32)
        ideal_emb = ideal_emb / np.linalg.norm(ideal_emb)

        with patch("quarry.pipeline.filter.embed_posting") as mock_embed:
            mock_embed.return_value = ideal_emb
            result = filter_posting(
                raw, ideal_emb, threshold=0.3, blocklist=[]
            )

        assert isinstance(result, FilterResult)
        assert result.passed is True
        assert result.skip_reason is None
        assert result.similarity_score is not None

    def test_blocks_low_similarity(self):
        from unittest.mock import patch

        raw = RawPosting(
            company_id=1,
            title="Line Cook",
            url="https://example.com/2",
            description="Prepare meals in kitchen",
            source_type="lever",
        )
        ideal_emb = np.zeros(384, dtype=np.float32)
        ideal_emb[0] = 1.0

        posting_emb = np.zeros(384, dtype=np.float32)
        posting_emb[200] = 1.0

        with patch("quarry.pipeline.filter.embed_posting") as mock_embed:
            mock_embed.return_value = posting_emb
            result = filter_posting(
                raw, ideal_emb, threshold=0.58, blocklist=[]
            )

        assert result.passed is False
        assert result.skip_reason == "low_similarity"

    def test_blocks_blocklisted_keyword(self):
        from unittest.mock import patch

        raw = RawPosting(
            company_id=1,
            title="Staffing Agency Recruiter",
            url="https://example.com/3",
            description="Recruit for staffing agency",
            source_type="greenhouse",
        )
        ideal_emb = np.ones(384, dtype=np.float32)
        ideal_emb = ideal_emb / np.linalg.norm(ideal_emb)

        with patch("quarry.pipeline.filter.embed_posting") as mock_embed:
            mock_embed.return_value = ideal_emb.copy()
            result = filter_posting(
                raw, ideal_emb, threshold=0.3, blocklist=["staffing agency"]
            )

        assert result.passed is False
        assert result.skip_reason == "blocklist"

    def test_returns_similarity_score_even_on_block(self):
        from unittest.mock import patch

        raw = RawPosting(
            company_id=1,
            title="Staffing Agency Role",
            url="https://example.com/4",
            source_type="greenhouse",
        )
        ideal_emb = np.ones(384, dtype=np.float32)
        ideal_emb = ideal_emb / np.linalg.norm(ideal_emb)

        with patch("quarry.pipeline.filter.embed_posting") as mock_embed:
            mock_embed.return_value = ideal_emb.copy()
            result = filter_posting(
                raw, ideal_emb, threshold=0.3, blocklist=["staffing agency"]
            )

        assert result.similarity_score is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_pipeline_filter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.pipeline.filter'`

- [ ] **Step 3: Implement filter module**

Create `quarry/pipeline/filter.py`:

```python
"""Similarity filtering and keyword blocklist for job postings.

Scores postings against the ideal role embedding using cosine similarity,
then applies a keyword blocklist to reject irrelevant postings.
"""

import logging

import numpy as np

from quarry.models import FilterResult, RawPosting
from quarry.pipeline.embedder import embed_posting

log = logging.getLogger(__name__)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        a: First vector.
        b: Second vector.

    Returns:
        Cosine similarity in [-1, 1]. Returns 0.0 if either vector is zero.
    """
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def score_similarity(
    posting_embedding: np.ndarray, ideal_embedding: np.ndarray
) -> float:
    """Score a posting's relevance against the ideal role embedding.

    Args:
        posting_embedding: Embedding of the job posting.
        ideal_embedding: Embedding of the ideal role description.

    Returns:
        Cosine similarity score in [-1, 1]. Higher = more relevant.
    """
    return cosine_similarity(posting_embedding, ideal_embedding)


def apply_keyword_blocklist(
    posting: RawPosting, blocklist: list[str]
) -> bool:
    """Check if a posting passes the keyword blocklist.

    A posting fails if any blocklisted phrase appears as a case-insensitive
    substring in the title, description, or location.

    Args:
        posting: RawPosting to check.
        blocklist: List of keyword phrases to reject.

    Returns:
        True if the posting passes (no blocklisted keywords found),
        False if it should be filtered out.
    """
    if not blocklist:
        return True

    text = " ".join(
        filter(None, [posting.title, posting.description, posting.location])
    ).lower()

    for phrase in blocklist:
        if phrase.lower() in text:
            log.debug("Blocklisted posting '%s': matched '%s'", posting.title, phrase)
            return False

    return True


def filter_posting(
    posting: RawPosting,
    ideal_embedding: np.ndarray,
    threshold: float | None = None,
    blocklist: list[str] | None = None,
) -> FilterResult:
    """Filter a single posting through similarity scoring and blocklist.

    Pipeline: embed posting → score similarity → check blocklist → return result.

    The similarity score is always computed and included in the result,
    even if the posting is blocked. Blocked postings get skip_reason set.

    Args:
        posting: RawPosting to evaluate.
        ideal_embedding: Embedding of the ideal role description.
        threshold: Minimum cosine similarity to pass. If None, reads from
                   config settings (default 0.58 in config.yaml).
        blocklist: Keyword phrases that cause rejection.

    Returns:
        FilterResult with pass/fail status, skip reason, and similarity score.
    """
    if threshold is None:
        from quarry.config import settings
        threshold = settings.similarity_threshold
    blocklist = blocklist or []

    posting_embedding = embed_posting(posting)
    similarity = score_similarity(posting_embedding, ideal_embedding)

    if not apply_keyword_blocklist(posting, blocklist):
        return FilterResult(
            posting=posting,
            passed=False,
            skip_reason="blocklist",
            similarity_score=round(similarity, 4),
        )

    if similarity < threshold:
        return FilterResult(
            posting=posting,
            passed=False,
            skip_reason="low_similarity",
            similarity_score=round(similarity, 4),
        )

    return FilterResult(
        posting=posting,
        passed=True,
        skip_reason=None,
        similarity_score=round(similarity, 4),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_pipeline_filter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add quarry/pipeline/filter.py tests/test_pipeline_filter.py
git commit -m "feat: add similarity scoring and keyword blocklist filter"
```

---

### Task 3: Integration — filter pipeline wiring and DB storage of embeddings

**Files:**
- Modify: `quarry/store/db.py`
- Modify: `quarry/pipeline/extract.py` (minor: make `extract` importable from pipeline)
- Create: `tests/test_m4_integration.py`

This task wires the full M4 flow: extract → embed → filter → store with score and embedding.

- [ ] **Step 1: Add `update_posting_embedding` and `update_posting_similarity` to Database**

Add two methods to `quarry/store/db.py` after the `posting_exists_by_url` method (around line 151):

```python
    def update_posting_embedding(self, posting_id: int, embedding: bytes) -> None:
        """Store the embedding vector for a posting."""
        sql = "UPDATE job_postings SET embedding = ? WHERE id = ?"
        self.execute(sql, (embedding, posting_id))

    def update_posting_similarity(self, posting_id: int, score: float) -> None:
        """Store the similarity score for a posting."""
        sql = "UPDATE job_postings SET similarity_score = ? WHERE id = ?"
        self.execute(sql, (score, posting_id))
```

- [ ] **Step 2: Write integration test**

Create `tests/test_m4_integration.py`:

```python
"""Integration tests for the full M4 pipeline: extract → embed → filter → store."""

import numpy as np
import pytest

from quarry.models import RawPosting
from quarry.pipeline.embedder import (
    deserialize_embedding,
    embed_posting,
    get_ideal_embedding,
    serialize_embedding,
    set_ideal_embedding,
)
from quarry.pipeline.extract import extract
from quarry.pipeline.filter import filter_posting
from quarry.store.db import Database, init_db


@pytest.fixture
def db(tmp_path):
    return init_db(str(tmp_path / "test.db"))


@pytest.fixture
def seed_company(db):
    from quarry.models import Company

    company = Company(name="TestCorp", ats_type="greenhouse", ats_slug="testcorp")
    company_id = db.insert_company(company)
    return company_id


class TestEndToEndPipeline:
    def test_extract_embed_filter_store(self, db, seed_company):
        ideal_desc = "Senior people analytics leader at a growth-stage tech company"
        ideal_emb = set_ideal_embedding(db, ideal_desc)

        raw = RawPosting(
            company_id=seed_company,
            title="Senior People Analytics Manager",
            url="https://example.com/job/1",
            description="Lead the people analytics function at our company",
            location="Remote, US",
            source_type="greenhouse",
        )

        posting = extract(raw)
        assert posting.remote is True

        result = filter_posting(raw, ideal_emb, threshold=0.3, blocklist=[])
        assert result.passed is True
        assert result.similarity_score is not None
        assert result.similarity_score > 0.3

        posting.similarity_score = result.similarity_score

        posting_id = db.insert_posting(posting)
        assert posting_id > 0

        db.update_posting_similarity(posting_id, result.similarity_score)

        fetched_postings = db.get_postings(status="new")
        assert len(fetched_postings) >= 1
        fetched = fetched_postings[0]
        assert fetched.similarity_score == result.similarity_score

    def test_blocklisted_posting_rejected(self, db, seed_company):
        ideal_emb = np.ones(384, dtype=np.float32)
        ideal_emb = ideal_emb / np.linalg.norm(ideal_emb)

        raw = RawPosting(
            company_id=seed_company,
            title="Staffing Agency Recruiter",
            url="https://example.com/job/2",
            description="Work at a staffing agency placing candidates",
            source_type="greenhouse",
        )

        result = filter_posting(
            raw, ideal_emb, threshold=0.3, blocklist=["staffing agency"]
        )
        assert result.passed is False
        assert result.skip_reason == "blocklist"

    def test_low_similarity_rejected(self, db, seed_company):
        ideal_emb = np.zeros(384, dtype=np.float32)
        ideal_emb[0] = 1.0

        raw = RawPosting(
            company_id=seed_company,
            title="Line Cook",
            url="https://example.com/job/3",
            description="Prepare food in restaurant kitchen",
            source_type="lever",
        )

        result = filter_posting(raw, ideal_emb, threshold=0.58, blocklist=[])
        assert result.passed is False
        assert result.skip_reason == "low_similarity"

    def test_ideal_embedding_persists(self, db):
        desc = "Senior people analytics or HR technology leader"
        emb = set_ideal_embedding(db, desc)

        retrieved = get_ideal_embedding(db)
        assert retrieved is not None
        assert np.allclose(emb, retrieved)

    def test_embedding_serialization_roundtrip(self):
        emb = np.random.rand(384).astype(np.float32)
        emb = emb / np.linalg.norm(emb)

        serialized = serialize_embedding(emb)
        assert isinstance(serialized, bytes)

        deserialized = deserialize_embedding(serialized)
        assert np.allclose(emb, deserialized)

    def test_store_and_retrieve_embedding(self, db, seed_company):
        emb = np.random.rand(384).astype(np.float32)
        serialized = serialize_embedding(emb)

        from quarry.models import JobPosting

        posting = JobPosting(
            company_id=seed_company,
            title="Test Engineer",
            title_hash="abc123",
            url="https://example.com/job/embed",
            source_type="greenhouse",
            similarity_score=0.75,
            embedding=serialized,
        )

        posting_id = db.insert_posting(posting)
        assert posting_id > 0

        db.update_posting_embedding(posting_id, serialized)

        rows = db.execute(
            "SELECT embedding FROM job_postings WHERE id = ?", (posting_id,)
        )
        assert rows is not None
        stored = rows[0]["embedding"]
        retrieved = deserialize_embedding(stored)
        assert np.allclose(emb, retrieved)

    def test_dedup_prevents_duplicate_insert(self, db, seed_company):
        from quarry.models import JobPosting

        posting = JobPosting(
            company_id=seed_company,
            title="Duplicate Engineer",
            title_hash="hash123",
            url="https://example.com/job/dup",
            source_type="greenhouse",
        )

        db.insert_posting(posting)
        assert db.posting_exists(seed_company, "hash123") is True
        assert db.posting_exists_by_url("https://example.com/job/dup") is True
```

- [ ] **Step 3: Run integration tests to verify they fail**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_m4_integration.py -v`
Expected: FAIL with `ModuleNotFoundError` or `AttributeError` for `update_posting_embedding`

- [ ] **Step 4: Run integration tests to verify they pass**

Run: `PYTHONPATH=/home/kurtt/job-search pytest tests/test_m4_integration.py -v`
Expected: All PASS

- [ ] **Step 5: Run the full test suite**

Run: `PYTHONPATH=/home/kurtt/job-search pytest -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add quarry/store/db.py tests/test_m4_integration.py
git commit -m "feat: add embedding DB storage and M4 integration pipeline"
```

---

### Task 4: CLI entrypoint for embedding the ideal role

**Files:**
- Create: `quarry/pipeline/__main__.py`

This adds `python -m quarry.pipeline embed-ideal` so you can seed the ideal role embedding from the command line.

- [ ] **Step 1: Write the CLI entrypoint**

Create `quarry/pipeline/__main__.py`:

```python
"""Pipeline CLI entrypoint.

Usage:
    python -m quarry.pipeline embed-ideal   # Embed ideal role description from config
"""

import click

from quarry.config import settings
from quarry.store.db import get_db


@click.group()
def cli():
    """Pipeline commands for embedding and filtering."""
    pass


@cli.command()
def embed_ideal():
    """Embed the ideal role description and store in DB."""
    db = get_db()
    desc = settings.ideal_role_description
    if not desc:
        click.echo("Error: ideal_role_description is empty in config.")
        raise SystemExit(1)

    from quarry.pipeline.embedder import set_ideal_embedding

    embedding = set_ideal_embedding(db, desc)
    threshold = settings.similarity_threshold
    click.echo(
        f"Ideal role description embedded successfully.\n"
        f"  Description: {desc[:80]}...\n"
        f"  Embedding dim: {embedding.shape[0]}\n"
        f"  Similarity threshold: {threshold}"
    )


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Test the CLI command**

Run: `PYTHONPATH=/home/kurtt/job-search python -m quarry.pipeline embed-ideal`
Expected: Prints confirmation message with embedding dimension and threshold

- [ ] **Step 3: Commit**

```bash
git add quarry/pipeline/__main__.py
git commit -m "feat: add pipeline CLI for ideal role embedding"
```

---

### Task 5: Update pipeline `__init__.py` for convenient imports

**Files:**
- Modify: `quarry/pipeline/__init__.py`

- [ ] **Step 1: Add public API to pipeline __init__.py**

Update `quarry/pipeline/__init__.py` (currently empty):

```python
"""Quarry pipeline: extraction, embedding, and filtering."""

from quarry.pipeline.embedder import embed_posting, embed_text, get_embedding_dim, get_ideal_embedding, set_ideal_embedding
from quarry.pipeline.extract import extract
from quarry.pipeline.filter import apply_keyword_blocklist, filter_posting, score_similarity
```

- [ ] **Step 2: Verify imports work**

Run: `PYTHONPATH=/home/kurtt/job-search python -c "from quarry.pipeline import extract, embed_text, filter_posting; print('OK')"`
Expected: Prints `OK`

- [ ] **Step 3: Run full test suite**

Run: `PYTHONPATH=/home/kurtt/job-search pytest -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add quarry/pipeline/__init__.py
git commit -m "feat: expose pipeline public API in __init__"
```

---

## Acceptance Criteria Verification

After all tasks are complete, verify:

```bash
PYTHONPATH=/home/kurtt/job-search pytest tests/test_pipeline_embedder.py tests/test_pipeline_filter.py tests/test_m4_integration.py -v
```

All tests must pass. Then run the full suite:

```bash
PYTHONPATH=/home/kurtt/job-search pytest -v
```

No regressions.

The M4 acceptance test from TASKS.md: **"Given two postings (one clearly relevant, one not), scores are meaningfully different and threshold filtering works"** — covered by `TestScoreSimilarity.test_relevant_posting_high_score` and `TestFilterPosting.test_blocks_low_similarity`.