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
    dim = model.get_embedding_dimension()
    assert dim is not None, "Model returned None for embedding dimension"
    return dim


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
    embedding = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(embedding, dtype=np.float32)


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


def set_ideal_embedding(db, description: str, user_id: int = 1) -> np.ndarray:
    """Compute and store the ideal role embedding for a specific user.

    Args:
        db: Database instance.
        description: The ideal role description text.
        user_id: User to store the embedding for (default 1).

    Returns:
        The computed embedding vector.
    """
    embedding = embed_text(description)
    db.save_user_setting(
        user_id, "ideal_role_embedding", serialize_embedding(embedding).hex()
    )
    db.save_user_setting(user_id, "ideal_role_description", description)
    return embedding


def get_ideal_embedding(db, user_id: int = 1) -> np.ndarray | None:
    """Retrieve the stored ideal role embedding for a specific user.

    Args:
        db: Database instance.
        user_id: User to retrieve the embedding for (default 1).

    Returns:
        Stored embedding vector, or None if not set.
    """
    settings_raw = db.get_user_settings_raw(user_id)
    hex_str = settings_raw.get("ideal_role_embedding")
    if hex_str is None:
        return None
    raw = bytes.fromhex(hex_str)
    return deserialize_embedding(raw)
