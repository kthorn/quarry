"""Quarry pipeline: extraction, embedding, and filtering."""

from quarry.pipeline.embedder import (
    embed_posting,
    embed_text,
    get_embedding_dim,
    get_ideal_embedding,
    set_ideal_embedding,
)
from quarry.pipeline.extract import extract
from quarry.pipeline.filter import (
    apply_keyword_blocklist,
    filter_posting,
    score_similarity,
)
from quarry.pipeline.locations import parse_location

__all__ = [
    "embed_posting",
    "embed_text",
    "get_embedding_dim",
    "get_ideal_embedding",
    "set_ideal_embedding",
    "extract",
    "parse_location",
    "apply_keyword_blocklist",
    "filter_posting",
    "score_similarity",
]
