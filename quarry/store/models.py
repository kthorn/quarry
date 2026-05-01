# quarry/store/models.py
"""SQLAlchemy 2.0 ORM models for the multi-user database schema.

Each class maps to one table. Columns, relationships, constraints,
and indexes match the Phase 1 raw DDL exactly.

Separate from quarry/models.py (Pydantic API models).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    pass


# ── Shared Catalog Tables ───────────────────────────────────────


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(Text)
    careers_url: Mapped[Optional[str]] = mapped_column(Text)
    ats_type: Mapped[str] = mapped_column(Text, server_default=text("'unknown'"))
    ats_slug: Mapped[Optional[str]] = mapped_column(Text)
    resolve_status: Mapped[str] = mapped_column(
        Text, server_default=text("'unresolved'")
    )
    resolve_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "ats_type IN ('greenhouse','lever','ashby','generic','unknown')",
            name="ck_companies_ats_type",
        ),
        CheckConstraint(
            "resolve_status IN ('unresolved','resolved','failed')",
            name="ck_companies_resolve_status",
        ),
    )

    # Relationships
    postings: Mapped[list["JobPosting"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    crawl_runs: Mapped[list["CrawlRun"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    watchlist_items: Mapped[list["UserWatchlistItem"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_hash: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(Text)
    work_model: Mapped[Optional[str]] = mapped_column(Text)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    source_id: Mapped[Optional[str]] = mapped_column(Text)
    source_type: Mapped[Optional[str]] = mapped_column(Text)
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("company_id", "title_hash"),
        Index("idx_postings_company", "company_id"),
        Index("idx_postings_title_hash", "title_hash"),
        Index("idx_postings_work_model", "work_model"),
    )

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="postings")
    locations: Mapped[list["JobPostingLocation"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )
    posting_statuses: Mapped[list["UserPostingStatus"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )
    labels: Mapped[list["UserLabel"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )
    similarity_scores: Mapped[list["UserSimilarityScore"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )
    classifier_scores: Mapped[list["UserClassifierScore"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )
    enriched_entries: Mapped[list["UserEnrichedPosting"]] = relationship(
        back_populates="posting", cascade="all, delete-orphan"
    )


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    city: Mapped[Optional[str]] = mapped_column(Text)
    state: Mapped[Optional[str]] = mapped_column(Text)
    state_code: Mapped[Optional[str]] = mapped_column(Text)
    country: Mapped[Optional[str]] = mapped_column(Text)
    country_code: Mapped[Optional[str]] = mapped_column(Text)
    region: Mapped[Optional[str]] = mapped_column(Text)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    resolution_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'resolved'")
    )
    raw_fragment: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index("idx_locations_canonical", "canonical_name"),
        Index("idx_locations_country", "country_code"),
        Index("idx_locations_region", "region"),
        Index("idx_locations_city", "city"),
        Index("idx_locations_state", "state_code"),
    )

    # Relationships
    posting_links: Mapped[list["JobPostingLocation"]] = relationship(
        back_populates="location", cascade="all, delete-orphan"
    )


class JobPostingLocation(Base):
    __tablename__ = "job_posting_locations"

    posting_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        primary_key=True,
    )
    location_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("locations.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        Index("idx_jpl_posting", "posting_id"),
        Index("idx_jpl_location", "location_id"),
    )

    # Relationships
    posting: Mapped["JobPosting"] = relationship(back_populates="locations")
    location: Mapped["Location"] = relationship(back_populates="posting_links")


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[Optional[str]] = mapped_column(Text)
    postings_found: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    postings_new: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    company: Mapped["Company"] = relationship(back_populates="crawl_runs")


class ClassifierVersion(Base):
    __tablename__ = "classifier_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trained_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    training_samples: Mapped[Optional[int]] = mapped_column(Integer)
    positive_samples: Mapped[Optional[int]] = mapped_column(Integer)
    negative_samples: Mapped[Optional[int]] = mapped_column(Integer)
    cv_accuracy: Mapped[Optional[float]] = mapped_column(Float)
    cv_precision: Mapped[Optional[float]] = mapped_column(Float)
    cv_recall: Mapped[Optional[float]] = mapped_column(Float)
    model_path: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("0"))
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    classifier_scores: Mapped[list["UserClassifierScore"]] = relationship(
        back_populates="model_version"
    )


class AgentAction(Base):
    """WARNING: tool_args and tool_result may contain sensitive data
    (API keys, resume text, LLM prompts). Stored as plaintext.
    Encrypt or mask before multi-user deployment."""

    __tablename__ = "agent_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_args: Mapped[Optional[str]] = mapped_column(Text)
    tool_result: Mapped[Optional[str]] = mapped_column(Text)
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_agent_actions_run", "run_id"),
        Index("idx_agent_actions_time", "created_at"),
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── Per-User Tables ────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    watchlist_items: Mapped[list["UserWatchlistItem"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    posting_statuses: Mapped[list["UserPostingStatus"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    labels: Mapped[list["UserLabel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    search_queries: Mapped[list["UserSearchQuery"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    similarity_scores: Mapped[list["UserSimilarityScore"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    classifier_scores: Mapped[list["UserClassifierScore"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    enriched_entries: Mapped[list["UserEnrichedPosting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped[list["UserSetting"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserWatchlistItem(Base):
    __tablename__ = "user_watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    crawl_priority: Mapped[int] = mapped_column(Integer, server_default=text("5"))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    added_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "company_id"),
        Index("idx_watchlist_user", "user_id"),
        Index("idx_watchlist_company", "company_id"),
        Index("idx_watchlist_active", "user_id", "active"),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="watchlist_items")
    company: Mapped["Company"] = relationship(back_populates="watchlist_items")


class UserPostingStatus(Base):
    __tablename__ = "user_posting_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    posting_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[Optional[str]] = mapped_column(Text, server_default=text("'new'"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "posting_id"),
        CheckConstraint(
            "status IN ('new','seen','applied','rejected','archived')",
            name="ck_posting_status_status",
        ),
        Index("idx_posting_status_user", "user_id"),
        Index("idx_posting_status_posting", "posting_id"),
        Index("idx_posting_status_status", "user_id", "status"),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="posting_statuses")
    posting: Mapped["JobPosting"] = relationship(back_populates="posting_statuses")


class UserLabel(Base):
    __tablename__ = "user_labels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    posting_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
    )
    signal: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    labeled_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    label_source: Mapped[str] = mapped_column(Text, server_default=text("'user'"))

    __table_args__ = (
        UniqueConstraint("user_id", "posting_id", "signal"),
        CheckConstraint(
            "signal IN ('positive','negative','applied','skip')",
            name="ck_user_labels_signal",
        ),
        Index("idx_labels_user", "user_id"),
        Index("idx_labels_posting", "posting_id"),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="labels")
    posting: Mapped["JobPosting"] = relationship(back_populates="labels")


class UserSearchQuery(Base):
    __tablename__ = "user_search_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    site: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("1"))
    added_reason: Mapped[Optional[str]] = mapped_column(Text)
    retired_reason: Mapped[Optional[str]] = mapped_column(Text)
    postings_found: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    positive_labels: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "query_text"),)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="search_queries")


class UserSimilarityScore(Base):
    __tablename__ = "user_similarity_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    posting_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
    )
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "posting_id"),
        Index("idx_sim_scores_user", "user_id"),
        Index("idx_sim_scores_posting", "posting_id"),
        Index("idx_sim_scores_value", "user_id", "similarity_score"),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="similarity_scores")
    posting: Mapped["JobPosting"] = relationship(back_populates="similarity_scores")


class UserClassifierScore(Base):
    __tablename__ = "user_classifier_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    posting_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
    )
    classifier_score: Mapped[float] = mapped_column(Float, nullable=False)
    model_version_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("classifier_versions.id", ondelete="SET NULL"),
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "posting_id"),
        Index("idx_cls_scores_user", "user_id"),
        Index("idx_cls_scores_posting", "posting_id"),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="classifier_scores")
    posting: Mapped["JobPosting"] = relationship(back_populates="classifier_scores")
    model_version: Mapped[Optional["ClassifierVersion"]] = relationship(
        back_populates="classifier_scores"
    )


class UserEnrichedPosting(Base):
    __tablename__ = "user_enriched_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    posting_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("job_postings.id", ondelete="CASCADE"),
        nullable=False,
    )
    fit_score: Mapped[Optional[int]] = mapped_column(Integer)
    role_tier: Mapped[Optional[str]] = mapped_column(Text)
    fit_reason: Mapped[Optional[str]] = mapped_column(Text)
    key_requirements: Mapped[Optional[str]] = mapped_column(Text)
    enriched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "posting_id"),
        Index("idx_enriched_user", "user_id"),
        Index("idx_enriched_posting", "posting_id"),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="enriched_entries")
    posting: Mapped["JobPosting"] = relationship(back_populates="enriched_entries")


class UserSetting(Base):
    __tablename__ = "user_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "key"),)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="settings")


# ── SQLite foreign key enforcement ──────────────────────────────


# This hook is registered by session.py when the engine is created.
# Defined here as a module-level utility for documentation/import.
def _pragma_foreign_keys_on(dbapi_connection, connection_record):
    """Event listener: enable SQLite foreign key enforcement on every connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()
