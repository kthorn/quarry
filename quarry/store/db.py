"""Database CRUD layer — SQLAlchemy ORM (Phase 3).

All named methods use self.engine + session_scope() internally.
No raw sqlite3 — execute(), executemany(), and get_connection() are removed.
Per-user methods default to user_id=1 for backward compatibility.
"""

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

import quarry.models as models
from quarry.store.session import get_engine, session_scope


class Database:
    def __init__(self, db_path_or_engine: str | Path | Engine):
        if isinstance(db_path_or_engine, Engine):
            self.engine = db_path_or_engine
        else:
            self.engine = get_engine(Path(db_path_or_engine))

    # ── Company methods ────────────────────────────────────────

    def insert_company(self, company: models.Company, user_id: int = 1) -> int:
        """Insert a company into the shared catalog and auto-add to user's watchlist."""
        from quarry.store.models import Company as ORMCompany
        from quarry.store.models import UserWatchlistItem as ORMWatchlist

        with session_scope(engine=self.engine) as session:
            orm_co = ORMCompany(
                name=company.name,
                domain=company.domain,
                careers_url=company.careers_url,
                ats_type=company.ats_type,
                ats_slug=company.ats_slug,
                resolve_status=company.resolve_status,
                resolve_attempts=company.resolve_attempts,
            )
            session.add(orm_co)
            session.flush()
            company_id = orm_co.id

            session.add(
                ORMWatchlist(
                    user_id=user_id,
                    company_id=company_id,
                    active=True,
                    crawl_priority=5,
                )
            )
            return company_id

    def get_company(self, company_id: int) -> models.Company | None:
        from quarry.store.models import Company as ORMCompany

        with session_scope(engine=self.engine) as session:
            row = session.get(ORMCompany, company_id)
            if row is None:
                return None
            return models.Company.model_validate(row, from_attributes=True)

    def get_all_companies(
        self, active_only: bool = True, user_id: int = 1
    ) -> list[models.Company]:
        from quarry.store.models import Company as ORMCompany
        from quarry.store.models import UserWatchlistItem as ORMWatchlist

        with session_scope(engine=self.engine) as session:
            if active_only:
                stmt = (
                    select(ORMCompany)
                    .join(
                        ORMWatchlist,
                        and_(
                            ORMCompany.id == ORMWatchlist.company_id,
                            ORMWatchlist.user_id == user_id,
                        ),
                    )
                    .where(ORMWatchlist.active.is_(True))
                )
            else:
                stmt = select(ORMCompany)
            result = session.execute(stmt).scalars().all()
            return [
                models.Company.model_validate(c, from_attributes=True) for c in result
            ]

    def get_company_by_name(self, name: str) -> models.Company | None:
        from quarry.store.models import Company as ORMCompany

        with session_scope(engine=self.engine) as session:
            row = session.execute(
                select(ORMCompany).where(ORMCompany.name == name)
            ).scalar_one_or_none()
            if row is None:
                return None
            return models.Company.model_validate(row, from_attributes=True)

    def get_companies_by_resolve_status(self, status: str) -> list[models.Company]:
        from quarry.store.models import Company as ORMCompany

        with session_scope(engine=self.engine) as session:
            result = (
                session.execute(
                    select(ORMCompany).where(ORMCompany.resolve_status == status)
                )
                .scalars()
                .all()
            )
            return [
                models.Company.model_validate(c, from_attributes=True) for c in result
            ]

    def update_company(self, company: models.Company) -> None:
        """Update shared company fields. Per-user fields (active, crawl_priority,
        notes, added_reason) live on user_watchlist and are not touched here."""
        from quarry.store.models import Company as ORMCompany

        with session_scope(engine=self.engine) as session:
            stmt = (
                update(ORMCompany)
                .where(ORMCompany.id == company.id)
                .values(
                    name=company.name,
                    domain=company.domain,
                    careers_url=company.careers_url,
                    ats_type=company.ats_type,
                    ats_slug=company.ats_slug,
                    resolve_status=company.resolve_status,
                    resolve_attempts=company.resolve_attempts,
                    updated_at=func.now(),
                )
            )
            session.execute(stmt)

    # ── Posting methods ────────────────────────────────────────

    def insert_posting(self, posting: models.JobPosting, user_id: int = 1) -> int:
        """Insert a posting into the shared catalog and create user_posting_status."""
        from quarry.store.models import JobPosting as ORMPosting
        from quarry.store.models import UserPostingStatus as ORMStatus

        with session_scope(engine=self.engine) as session:
            orm_p = ORMPosting(
                company_id=posting.company_id,
                title=posting.title,
                title_hash=posting.title_hash,
                url=posting.url,
                description=posting.description,
                location=posting.location,
                work_model=posting.work_model,
                posted_at=posting.posted_at,
                source_id=posting.source_id,
                source_type=posting.source_type,
                embedding=posting.embedding,
            )
            session.add(orm_p)
            session.flush()

            session.add(
                ORMStatus(
                    user_id=user_id,
                    posting_id=orm_p.id,
                    status="new",
                )
            )
            return orm_p.id

    def posting_exists(self, company_id: int, title_hash: str) -> bool:
        from quarry.store.models import JobPosting as ORMPosting

        with session_scope(engine=self.engine) as session:
            result = session.execute(
                select(ORMPosting.id).where(
                    ORMPosting.company_id == company_id,
                    ORMPosting.title_hash == title_hash,
                )
            ).scalar_one_or_none()
            return result is not None

    def posting_exists_by_url(self, url: str) -> bool:
        from quarry.store.models import JobPosting as ORMPosting

        with session_scope(engine=self.engine) as session:
            result = session.execute(
                select(ORMPosting.id).where(ORMPosting.url == url)
            ).scalar_one_or_none()
            return result is not None

    def update_posting_embedding(self, posting_id: int, embedding: bytes) -> None:
        from quarry.store.models import JobPosting as ORMPosting

        with session_scope(engine=self.engine) as session:
            session.execute(
                update(ORMPosting)
                .where(ORMPosting.id == posting_id)
                .values(embedding=embedding)
            )

    def update_posting_similarity(
        self, posting_id: int, score: float, user_id: int = 1
    ) -> None:
        from quarry.store.models import UserSimilarityScore as ORMSimScore

        with session_scope(engine=self.engine) as session:
            session.execute(
                sqlite_insert(ORMSimScore)
                .values(
                    user_id=user_id,
                    posting_id=posting_id,
                    similarity_score=score,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "posting_id"],
                    set_=dict(similarity_score=score, computed_at=func.now()),
                )
            )

    def update_posting_similarities(
        self, posting_id_scores: list[tuple[int, float]], user_id: int = 1
    ) -> None:
        if not posting_id_scores:
            return
        from quarry.store.models import UserSimilarityScore as ORMSimScore

        with session_scope(engine=self.engine) as session:
            stmt = sqlite_insert(ORMSimScore).values(
                [
                    dict(user_id=user_id, posting_id=pid, similarity_score=score)
                    for pid, score in posting_id_scores
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "posting_id"],
                set_=dict(
                    similarity_score=stmt.excluded.similarity_score,
                    computed_at=func.now(),
                ),
            )
            session.execute(stmt)

    def get_all_postings_with_embeddings(self) -> list[models.JobPosting]:
        from quarry.store.models import JobPosting as ORMPosting

        with session_scope(engine=self.engine) as session:
            result = (
                session.execute(
                    select(ORMPosting).where(ORMPosting.embedding.isnot(None))
                )
                .scalars()
                .all()
            )
            return [
                models.JobPosting.model_validate(p, from_attributes=True)
                for p in result
            ]

    def get_postings(
        self, status: str | None = None, limit: int = 100, user_id: int = 1
    ) -> list[models.JobPosting]:
        from quarry.store.models import JobPosting as ORMPosting
        from quarry.store.models import UserPostingStatus as ORMStatus

        with session_scope(engine=self.engine) as session:
            if status is not None:
                if status == "new":
                    stmt = (
                        select(ORMPosting)
                        .outerjoin(
                            ORMStatus,
                            and_(
                                ORMPosting.id == ORMStatus.posting_id,
                                ORMStatus.user_id == user_id,
                            ),
                        )
                        .where(
                            or_(
                                ORMStatus.status == "new",
                                ORMStatus.status.is_(None),
                            )
                        )
                        .limit(limit)
                    )
                else:
                    stmt = (
                        select(ORMPosting)
                        .join(
                            ORMStatus,
                            and_(
                                ORMPosting.id == ORMStatus.posting_id,
                                ORMStatus.user_id == user_id,
                            ),
                        )
                        .where(ORMStatus.status == status)
                        .limit(limit)
                    )
            else:
                stmt = select(ORMPosting).limit(limit)

            result = session.execute(stmt).scalars().all()
            return [
                models.JobPosting.model_validate(p, from_attributes=True)
                for p in result
            ]

    def get_posting_by_id(self, posting_id: int) -> models.JobPosting | None:
        from quarry.store.models import JobPosting as ORMPosting

        with session_scope(engine=self.engine) as session:
            row = session.get(ORMPosting, posting_id)
            if row is None:
                return None
            return models.JobPosting.model_validate(row, from_attributes=True)

    def get_postings_for_search(
        self, status: str | None = None, user_id: int = 1
    ) -> list[tuple[models.JobPosting, str]]:
        from quarry.store.models import Company as ORMCompany
        from quarry.store.models import JobPosting as ORMPosting
        from quarry.store.models import UserPostingStatus as ORMStatus

        with session_scope(engine=self.engine) as session:
            stmt = (
                select(ORMPosting, ORMCompany.name)
                .join(ORMCompany, ORMPosting.company_id == ORMCompany.id)
                .where(ORMPosting.embedding.isnot(None))
            )
            if status is not None:
                if status == "new":
                    stmt = stmt.outerjoin(
                        ORMStatus,
                        and_(
                            ORMPosting.id == ORMStatus.posting_id,
                            ORMStatus.user_id == user_id,
                        ),
                    ).where(
                        or_(
                            ORMStatus.status == "new",
                            ORMStatus.status.is_(None),
                        )
                    )
                else:
                    stmt = stmt.join(
                        ORMStatus,
                        and_(
                            ORMPosting.id == ORMStatus.posting_id,
                            ORMStatus.user_id == user_id,
                        ),
                    ).where(ORMStatus.status == status)

            result = session.execute(stmt).all()
            out = []
            for posting, company_name in result:
                out.append(
                    (
                        models.JobPosting.model_validate(posting, from_attributes=True),
                        company_name,
                    )
                )
            return out

    def mark_postings_seen(self, posting_ids: list[int], user_id: int = 1) -> None:
        if not posting_ids:
            return
        from quarry.store.models import UserPostingStatus as ORMStatus

        now = datetime.now(timezone.utc)
        with session_scope(engine=self.engine) as session:
            stmt = sqlite_insert(ORMStatus).values(
                [
                    dict(
                        user_id=user_id,
                        posting_id=pid,
                        status="seen",
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    for pid in posting_ids
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "posting_id"],
                set_=dict(status="seen", last_seen_at=now),
            )
            session.execute(stmt)

    def update_posting_status(
        self, posting_id: int, status: str, user_id: int = 1
    ) -> None:
        from quarry.store.models import UserPostingStatus as ORMStatus

        now = datetime.now(timezone.utc)
        with session_scope(engine=self.engine) as session:
            session.execute(
                sqlite_insert(ORMStatus)
                .values(
                    user_id=user_id,
                    posting_id=posting_id,
                    status=status,
                    first_seen_at=now,
                    last_seen_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "posting_id"],
                    set_=dict(status=status, last_seen_at=now),
                )
            )

    def count_postings(self, status: str | None = None, user_id: int = 1) -> int:
        from quarry.store.models import JobPosting as ORMPosting
        from quarry.store.models import UserPostingStatus as ORMStatus

        with session_scope(engine=self.engine) as session:
            if status is None:
                result = session.execute(select(func.count(ORMPosting.id))).scalar()
            elif status == "new":
                result = session.execute(
                    select(func.count(ORMPosting.id))
                    .outerjoin(
                        ORMStatus,
                        and_(
                            ORMPosting.id == ORMStatus.posting_id,
                            ORMStatus.user_id == user_id,
                        ),
                    )
                    .where(
                        or_(
                            ORMStatus.status == "new",
                            ORMStatus.status.is_(None),
                        )
                    )
                ).scalar()
            else:
                result = session.execute(
                    select(func.count(ORMPosting.id))
                    .join(
                        ORMStatus,
                        and_(
                            ORMPosting.id == ORMStatus.posting_id,
                            ORMStatus.user_id == user_id,
                        ),
                    )
                    .where(ORMStatus.status == status)
                ).scalar()
            return result or 0

    # ── Label methods ──────────────────────────────────────────

    def insert_label(self, label: models.UserLabel, user_id: int = 1) -> int:
        from quarry.store.models import UserLabel as ORMLabel

        with session_scope(engine=self.engine) as session:
            orm_label = ORMLabel(
                user_id=label.user_id if label.user_id is not None else user_id,
                posting_id=label.posting_id,
                signal=label.signal,
                notes=label.notes,
                label_source=label.label_source,
            )
            session.add(orm_label)
            session.flush()
            return orm_label.id

    def get_labels_for_posting(
        self, posting_id: int, user_id: int = 1
    ) -> list[models.UserLabel]:
        from quarry.store.models import UserLabel as ORMLabel

        with session_scope(engine=self.engine) as session:
            result = (
                session.execute(
                    select(ORMLabel)
                    .where(
                        ORMLabel.posting_id == posting_id,
                        ORMLabel.user_id == user_id,
                    )
                    .order_by(ORMLabel.labeled_at.desc())
                )
                .scalars()
                .all()
            )
            return [
                models.UserLabel.model_validate(label, from_attributes=True)
                for label in result
            ]

    # ── Crawl run methods ──────────────────────────────────────

    def insert_crawl_run(self, run: models.CrawlRun) -> int:
        from quarry.store.models import CrawlRun as ORMCrawlRun

        with session_scope(engine=self.engine) as session:
            orm_run = ORMCrawlRun(
                company_id=run.company_id,
                started_at=run.started_at,
                completed_at=run.completed_at,
                status=run.status,
                postings_found=run.postings_found,
                postings_new=run.postings_new,
                error_message=run.error_message,
            )
            session.add(orm_run)
            session.flush()
            return orm_run.id

    # ── Search query methods ───────────────────────────────────

    def insert_search_query(
        self, query: models.UserSearchQuery, user_id: int = 1
    ) -> int:
        from quarry.store.models import UserSearchQuery as ORMSearchQuery

        with session_scope(engine=self.engine) as session:
            orm_q = ORMSearchQuery(
                user_id=query.user_id if query.user_id is not None else user_id,
                query_text=query.query_text,
                site=query.site,
                active=query.active,
                added_reason=query.added_reason,
                retired_reason=query.retired_reason,
                postings_found=query.postings_found,
                positive_labels=query.positive_labels,
            )
            session.add(orm_q)
            session.flush()
            return orm_q.id

    def get_active_search_queries(
        self, user_id: int = 1
    ) -> list[models.UserSearchQuery]:
        from quarry.store.models import UserSearchQuery as ORMSearchQuery

        with session_scope(engine=self.engine) as session:
            result = (
                session.execute(
                    select(ORMSearchQuery).where(
                        ORMSearchQuery.active.is_(True),
                        ORMSearchQuery.user_id == user_id,
                    )
                )
                .scalars()
                .all()
            )
            return [
                models.UserSearchQuery.model_validate(q, from_attributes=True)
                for q in result
            ]

    # ── Agent action methods ───────────────────────────────────

    def insert_agent_action(self, action: models.AgentAction) -> int:
        from quarry.store.models import AgentAction as ORMAction

        with session_scope(engine=self.engine) as session:
            orm_action = ORMAction(
                run_id=action.run_id,
                tool_name=action.tool_name,
                tool_args=action.tool_args,
                tool_result=action.tool_result,
                rationale=action.rationale,
            )
            session.add(orm_action)
            session.flush()
            return orm_action.id

    def get_agent_actions(self, limit: int = 50) -> list[models.AgentAction]:
        from quarry.store.models import AgentAction as ORMAction

        with session_scope(engine=self.engine) as session:
            result = (
                session.execute(
                    select(ORMAction).order_by(ORMAction.created_at.desc()).limit(limit)
                )
                .scalars()
                .all()
            )
            return [
                models.AgentAction.model_validate(a, from_attributes=True)
                for a in result
            ]

    # ── Company name helper ────────────────────────────────────

    def get_company_name(self, company_id: int) -> str | None:
        from quarry.store.models import Company as ORMCompany

        with session_scope(engine=self.engine) as session:
            result = session.execute(
                select(ORMCompany.name).where(ORMCompany.id == company_id)
            ).scalar_one_or_none()
            return result

    # ── Location methods ───────────────────────────────────────

    def get_or_create_location(self, parsed) -> int:
        from quarry.store.models import Location as ORMLocation

        with session_scope(engine=self.engine) as session:
            existing = session.execute(
                select(ORMLocation.id).where(
                    ORMLocation.canonical_name == parsed.canonical_name
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing

            loc = ORMLocation(
                canonical_name=parsed.canonical_name,
                city=parsed.city,
                state=parsed.state,
                state_code=parsed.state_code,
                country=parsed.country,
                country_code=parsed.country_code,
                region=parsed.region,
                latitude=parsed.latitude,
                longitude=parsed.longitude,
                resolution_status=parsed.resolution_status,
                raw_fragment=parsed.raw_fragment,
            )
            session.add(loc)
            session.flush()
            return loc.id

    def link_posting_location(self, posting_id: int, location_id: int) -> None:
        from quarry.store.models import JobPostingLocation

        with session_scope(engine=self.engine) as session:
            session.execute(
                sqlite_insert(JobPostingLocation)
                .values(posting_id=posting_id, location_id=location_id)
                .on_conflict_do_nothing(
                    index_elements=["posting_id", "location_id"],
                )
            )

    def get_postings_by_work_model(self, work_model: str) -> list[models.JobPosting]:
        from quarry.store.models import JobPosting as ORMPosting

        with session_scope(engine=self.engine) as session:
            result = (
                session.execute(
                    select(ORMPosting).where(ORMPosting.work_model == work_model)
                )
                .scalars()
                .all()
            )
            return [
                models.JobPosting.model_validate(p, from_attributes=True)
                for p in result
            ]

    def get_postings_by_location(self, canonical_name: str) -> list[models.JobPosting]:
        from quarry.store.models import JobPosting as ORMPosting
        from quarry.store.models import JobPostingLocation
        from quarry.store.models import Location as ORMLocation

        with session_scope(engine=self.engine) as session:
            result = (
                session.execute(
                    select(ORMPosting)
                    .join(
                        JobPostingLocation,
                        ORMPosting.id == JobPostingLocation.posting_id,
                    )
                    .join(ORMLocation, JobPostingLocation.location_id == ORMLocation.id)
                    .where(ORMLocation.canonical_name == canonical_name)
                )
                .scalars()
                .all()
            )
            return [
                models.JobPosting.model_validate(p, from_attributes=True)
                for p in result
            ]

    def get_postings_by_region(self, region: str) -> list[models.JobPosting]:
        from quarry.store.models import JobPosting as ORMPosting
        from quarry.store.models import JobPostingLocation
        from quarry.store.models import Location as ORMLocation

        with session_scope(engine=self.engine) as session:
            result = (
                session.execute(
                    select(ORMPosting)
                    .distinct()
                    .join(
                        JobPostingLocation,
                        ORMPosting.id == JobPostingLocation.posting_id,
                    )
                    .join(ORMLocation, JobPostingLocation.location_id == ORMLocation.id)
                    .where(ORMLocation.region == region)
                )
                .scalars()
                .all()
            )
            return [
                models.JobPosting.model_validate(p, from_attributes=True)
                for p in result
            ]

    # ── User Settings methods ──────────────────────────────────

    def save_user_setting(self, user_id: int, key: str, value: str) -> None:
        from quarry.store.models import UserSetting as ORMUserSetting

        with session_scope(engine=self.engine) as session:
            session.execute(
                sqlite_insert(ORMUserSetting)
                .values(user_id=user_id, key=key, value=value, updated_at=func.now())
                .on_conflict_do_update(
                    index_elements=["user_id", "key"],
                    set_=dict(value=value, updated_at=func.now()),
                )
            )

    def get_user_settings_raw(self, user_id: int) -> dict[str, str | None]:
        """Return all user_settings as a dict. Values may be None if
        the setting column is nullable (user_settings.value is Optional[str]).
        Callers should handle missing or None values."""
        from quarry.store.models import UserSetting as ORMUserSetting

        with session_scope(engine=self.engine) as session:
            result = session.execute(
                select(ORMUserSetting.key, ORMUserSetting.value).where(
                    ORMUserSetting.user_id == user_id
                )
            ).all()
            return {row.key: row.value for row in result}

    def get_postings_with_scores(
        self,
        user_id: int = 1,
        status: str = "new",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        from quarry.store.models import Company as ORMCompany
        from quarry.store.models import JobPosting as ORMPosting
        from quarry.store.models import UserClassifierScore as ORMClsScore
        from quarry.store.models import UserEnrichedPosting as ORMEnriched
        from quarry.store.models import UserPostingStatus as ORMStatus
        from quarry.store.models import UserSimilarityScore as ORMSimScore

        stmt = (
            select(
                ORMPosting.id,
                ORMPosting.company_id,
                ORMPosting.title,
                ORMPosting.url,
                ORMPosting.description,
                ORMPosting.location,
                ORMPosting.work_model,
                ORMPosting.posted_at,
                ORMPosting.source_id,
                ORMPosting.source_type,
                ORMCompany.name.label("company_name"),
                func.coalesce(ORMStatus.status, "new").label("status"),
                func.coalesce(ORMSimScore.similarity_score, 0.0).label(
                    "similarity_score"
                ),
                func.coalesce(ORMClsScore.classifier_score, 0.0).label(
                    "classifier_score"
                ),
                func.coalesce(ORMEnriched.fit_score, 0).label("fit_score"),
                ORMEnriched.role_tier,
                ORMEnriched.fit_reason,
            )
            .join(ORMCompany, ORMPosting.company_id == ORMCompany.id)
            .outerjoin(
                ORMStatus,
                and_(
                    ORMPosting.id == ORMStatus.posting_id,
                    ORMStatus.user_id == user_id,
                ),
            )
            .outerjoin(
                ORMSimScore,
                and_(
                    ORMPosting.id == ORMSimScore.posting_id,
                    ORMSimScore.user_id == user_id,
                ),
            )
            .outerjoin(
                ORMClsScore,
                and_(
                    ORMPosting.id == ORMClsScore.posting_id,
                    ORMClsScore.user_id == user_id,
                ),
            )
            .outerjoin(
                ORMEnriched,
                and_(
                    ORMPosting.id == ORMEnriched.posting_id,
                    ORMEnriched.user_id == user_id,
                ),
            )
        )

        if status == "new":
            stmt = stmt.where(
                or_(
                    ORMStatus.status == "new",
                    ORMStatus.status.is_(None),
                )
            )
        else:
            stmt = stmt.where(ORMStatus.status == status)

        stmt = (
            stmt.order_by(func.coalesce(ORMSimScore.similarity_score, 0.0).desc())
            .limit(limit)
            .offset(offset)
        )

        with session_scope(engine=self.engine) as session:
            result = session.execute(stmt).all()
            return [dict(row._mapping) for row in result]

    def count_postings_by_watchlist(
        self,
        user_id: int = 1,
        status: str | None = None,
    ) -> int:
        """Count postings from user's watchlist, optionally filtered by status."""
        from quarry.store.models import Company as ORMCompany
        from quarry.store.models import JobPosting as ORMPosting
        from quarry.store.models import UserPostingStatus as ORMStatus
        from quarry.store.models import UserWatchlistItem as ORMWatchlist

        stmt = (
            select(func.count(ORMPosting.id))
            .join(ORMCompany, ORMPosting.company_id == ORMCompany.id)
            .join(
                ORMWatchlist,
                and_(
                    ORMPosting.company_id == ORMWatchlist.company_id,
                    ORMWatchlist.user_id == user_id,
                    ORMWatchlist.active.is_(True),
                ),
            )
        )

        if status is not None:
            if status == "new":
                stmt = stmt.outerjoin(
                    ORMStatus,
                    and_(
                        ORMPosting.id == ORMStatus.posting_id,
                        ORMStatus.user_id == user_id,
                    ),
                ).where(
                    or_(
                        ORMStatus.status == "new",
                        ORMStatus.status.is_(None),
                    )
                )
            else:
                stmt = stmt.join(
                    ORMStatus,
                    and_(
                        ORMPosting.id == ORMStatus.posting_id,
                        ORMStatus.user_id == user_id,
                    ),
                ).where(ORMStatus.status == status)

        with session_scope(engine=self.engine) as session:
            result = session.execute(stmt).scalar()
            return result or 0

    # ── Watchlist methods ───────────────────────────────────────

    def get_watchlist(
        self,
        user_id: int = 1,
        active_only: bool = True,
    ) -> list[models.UserWatchlistItem]:
        from quarry.store.models import UserWatchlistItem as ORMWatchlist

        with session_scope(engine=self.engine) as session:
            stmt = select(ORMWatchlist).where(ORMWatchlist.user_id == user_id)
            if active_only:
                stmt = stmt.where(ORMWatchlist.active.is_(True))
            result = session.execute(stmt).scalars().all()
            return [
                models.UserWatchlistItem.model_validate(w, from_attributes=True)
                for w in result
            ]

    def upsert_watchlist_item(self, item: models.UserWatchlistItem) -> int:
        """Upsert a watchlist item. Returns lastrowid."""
        from quarry.store.models import UserWatchlistItem as ORMWatchlist

        with session_scope(engine=self.engine) as session:
            stmt = (
                sqlite_insert(ORMWatchlist)
                .values(
                    user_id=item.user_id,
                    company_id=item.company_id,
                    active=item.active,
                    crawl_priority=item.crawl_priority,
                    notes=item.notes,
                    added_reason=item.added_reason,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "company_id"],
                    set_=dict(
                        active=item.active,
                        crawl_priority=item.crawl_priority,
                        notes=item.notes,
                        added_reason=item.added_reason,
                        updated_at=func.now(),
                    ),
                )
            )
            result = session.execute(stmt)
            return result.lastrowid or 0  # type: ignore[union-attr]

    # ── Settings methods (system-level) ────────────────────────

    def get_setting(self, key: str) -> str | None:
        from quarry.store.models import SystemSetting as ORMSetting

        with session_scope(engine=self.engine) as session:
            row = session.get(ORMSetting, key)
            return row.value if row else None

    def set_setting(self, key: str, value: str) -> None:
        from quarry.store.models import SystemSetting as ORMSetting

        with session_scope(engine=self.engine) as session:
            session.execute(
                sqlite_insert(ORMSetting)
                .values(key=key, value=value, updated_at=func.now())
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_=dict(value=value, updated_at=func.now()),
                )
            )


# ── Module-level helpers ───────────────────────────────────────


def init_db(db_path: str | Path) -> Database:
    """Initialize database with schema (SQLAlchemy ORM) and return Database.

    Creates tables via Base.metadata.create_all and seeds the default
    user if not already present.
    """
    db_path = Path(db_path)

    from quarry.store.models import Base

    engine = get_engine(db_path)
    Base.metadata.create_all(engine, checkfirst=True)

    # Seed default user for single-user backward compat.
    with session_scope(engine=engine) as session:
        from quarry.store.models import User

        existing = session.execute(
            select(User).where(User.id == 1)
        ).scalar_one_or_none()
        if existing is None:
            session.add(User(id=1, email="default@local", name="Default User"))

    return Database(engine)


def get_db() -> Database:
    """Get database instance from config."""
    from quarry.config import settings

    return Database(settings.db_path)
