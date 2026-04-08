"""Extraction pipeline: RawPosting → JobPosting transformation.

This module handles:
- HTML tag stripping and whitespace normalization
- Remote work detection via keyword heuristics
- Location string normalization
- Title hashing for deduplication
"""
