import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import quarry.models as models
from quarry.store.schema import SCHEMA_SQL


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            return cursor.fetchall()

    def executemany(self, sql: str, params: list[tuple]) -> int:
        with self.get_connection() as conn:
            cursor = conn.executemany(sql, params)
            return cursor.rowcount

    def insert_company(self, company: models.Company) -> int:
        sql = """
            INSERT INTO companies (name, domain, careers_url, ats_type, ats_slug,
                resolve_status, resolve_attempts,
                active, crawl_priority, notes, added_by, added_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                sql,
                (
                    company.name,
                    company.domain,
                    company.careers_url,
                    company.ats_type,
                    company.ats_slug,
                    company.resolve_status,
                    company.resolve_attempts,
                    company.active,
                    company.crawl_priority,
                    company.notes,
                    company.added_by,
                    company.added_reason,
                ),
            )
            return cursor.lastrowid or 0

    def get_company(self, company_id: int) -> models.Company | None:
        sql = "SELECT * FROM companies WHERE id = ?"
        rows = self.execute(sql, (company_id,))
        if rows:
            return models.Company(**dict(rows[0]))
        return None

    def get_all_companies(self, active_only: bool = True) -> list[models.Company]:
        sql = "SELECT * FROM companies"
        if active_only:
            sql += " WHERE active = 1"
        rows = self.execute(sql)
        return [models.Company(**dict(row)) for row in rows]

    def get_company_by_name(self, name: str) -> models.Company | None:
        sql = "SELECT * FROM companies WHERE name = ?"
        rows = self.execute(sql, (name,))
        if rows:
            return models.Company(**dict(rows[0]))
        return None

    def get_companies_by_resolve_status(self, status: str) -> list[models.Company]:
        sql = "SELECT * FROM companies WHERE resolve_status = ?"
        rows = self.execute(sql, (status,))
        return [models.Company(**dict(row)) for row in rows]

    def migrate_resolve_columns(self) -> None:
        with self.get_connection() as conn:
            existing = {
                row[1]
                for row in conn.execute("PRAGMA table_info(companies)").fetchall()
            }
            if "resolve_status" not in existing:
                conn.execute(
                    "ALTER TABLE companies ADD COLUMN resolve_status TEXT DEFAULT 'unresolved'"
                )
            if "resolve_attempts" not in existing:
                conn.execute(
                    "ALTER TABLE companies ADD COLUMN resolve_attempts INTEGER DEFAULT 0"
                )
            conn.execute(
                "UPDATE companies SET resolve_status = 'resolved' "
                "WHERE domain IS NOT NULL AND careers_url IS NOT NULL AND ats_type != 'unknown'"
            )

    def update_company(self, company: models.Company) -> None:
        sql = """
            UPDATE companies SET name=?, domain=?, careers_url=?, ats_type=?,
                ats_slug=?, resolve_status=?, resolve_attempts=?,
                active=?, crawl_priority=?, notes=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """
        self.execute(
            sql,
            (
                company.name,
                company.domain,
                company.careers_url,
                company.ats_type,
                company.ats_slug,
                company.resolve_status,
                company.resolve_attempts,
                company.active,
                company.crawl_priority,
                company.notes,
                company.id,
            ),
        )

    def insert_posting(self, posting: models.JobPosting) -> int:
        sql = """
            INSERT INTO job_postings (company_id, title, title_hash, url, description,
                location, work_model, posted_at, source_id, source_type, similarity_score,
                classifier_score, embedding, fit_score, role_tier, fit_reason,
                key_requirements, enriched_at, status, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                sql,
                (
                    posting.company_id,
                    posting.title,
                    posting.title_hash,
                    posting.url,
                    posting.description,
                    posting.location,
                    posting.work_model,
                    posting.posted_at,
                    posting.source_id,
                    posting.source_type,
                    posting.similarity_score,
                    posting.classifier_score,
                    posting.embedding,
                    posting.fit_score,
                    posting.role_tier,
                    posting.fit_reason,
                    posting.key_requirements,
                    posting.enriched_at,
                    posting.status,
                    posting.first_seen_at,
                    posting.last_seen_at,
                ),
            )
            return cursor.lastrowid or 0

    def posting_exists(self, company_id: int, title_hash: str) -> bool:
        sql = "SELECT 1 FROM job_postings WHERE company_id = ? AND title_hash = ?"
        rows = self.execute(sql, (company_id, title_hash))
        return len(rows) > 0

    def posting_exists_by_url(self, url: str) -> bool:
        """Check if a posting with the given URL already exists.

        Args:
            url: Job posting URL to check

        Returns:
            True if posting exists, False otherwise
        """
        sql = "SELECT 1 FROM job_postings WHERE url = ?"
        rows = self.execute(sql, (url,))
        return len(rows) > 0

    def update_posting_embedding(self, posting_id: int, embedding: bytes) -> None:
        """Store the embedding vector for a posting."""
        sql = "UPDATE job_postings SET embedding = ? WHERE id = ?"
        self.execute(sql, (embedding, posting_id))

    def update_posting_similarity(self, posting_id: int, score: float) -> None:
        """Store the similarity score for a posting."""
        sql = "UPDATE job_postings SET similarity_score = ? WHERE id = ?"
        self.execute(sql, (score, posting_id))

    def update_posting_similarities(
        self, posting_id_scores: list[tuple[int, float]]
    ) -> None:
        """Bulk update similarity scores for multiple postings."""
        if not posting_id_scores:
            return
        sql = "UPDATE job_postings SET similarity_score = ? WHERE id = ?"
        self.executemany(sql, [(score, pid) for pid, score in posting_id_scores])

    def get_all_postings_with_embeddings(self) -> list[models.JobPosting]:
        """Get all postings that have embeddings stored."""
        sql = "SELECT * FROM job_postings WHERE embedding IS NOT NULL"
        rows = self.execute(sql)
        return [models.JobPosting(**dict(row)) for row in rows]

    def get_postings(
        self, status: str | None = None, limit: int = 100
    ) -> list[models.JobPosting]:
        sql = "SELECT * FROM job_postings"
        params = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " LIMIT ?"
        params = params + (limit,)
        rows = self.execute(sql, params)
        return [models.JobPosting(**dict(row)) for row in rows]

    def insert_label(self, label: models.Label) -> int:
        sql = """
            INSERT INTO labels (posting_id, signal, notes, labeled_at, label_source)
            VALUES (?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                sql,
                (
                    label.posting_id,
                    label.signal,
                    label.notes,
                    label.labeled_at,
                    label.label_source,
                ),
            )
            return cursor.lastrowid or 0

    def insert_crawl_run(self, run: models.CrawlRun) -> int:
        sql = """
            INSERT INTO crawl_runs (company_id, started_at, completed_at, status,
                postings_found, postings_new, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                sql,
                (
                    run.company_id,
                    run.started_at,
                    run.completed_at,
                    run.status,
                    run.postings_found,
                    run.postings_new,
                    run.error_message,
                ),
            )
            return cursor.lastrowid or 0

    def insert_search_query(self, query: models.SearchQuery) -> int:
        sql = """
            INSERT INTO search_queries (query_text, site, active, added_by,
                added_reason, postings_found, positive_labels)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                sql,
                (
                    query.query_text,
                    query.site,
                    query.active,
                    query.added_by,
                    query.added_reason,
                    query.postings_found,
                    query.positive_labels,
                ),
            )
            return cursor.lastrowid or 0

    def get_active_search_queries(self) -> list[models.SearchQuery]:
        sql = "SELECT * FROM search_queries WHERE active = 1"
        rows = self.execute(sql)
        return [models.SearchQuery(**dict(row)) for row in rows]

    def insert_agent_action(self, action: models.AgentAction) -> int:
        sql = """
            INSERT INTO agent_actions (run_id, tool_name, tool_args, tool_result, rationale)
            VALUES (?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                sql,
                (
                    action.run_id,
                    action.tool_name,
                    action.tool_args,
                    action.tool_result,
                    action.rationale,
                ),
            )
            return cursor.lastrowid or 0

    def get_recent_postings(
        self, limit: int = 100, status: str = "new", threshold: float | None = None
    ) -> list[models.JobPosting]:
        """Get recent postings ordered by similarity_score descending.

        Args:
            limit: Maximum number of postings to return.
            status: Filter by posting status.
            threshold: Minimum similarity score. If None, uses settings default.

        Returns:
            List of JobPosting objects sorted by similarity_score descending.
        """
        if threshold is None:
            from quarry.config import settings

            threshold = settings.similarity_threshold
        sql = """
            SELECT * FROM job_postings
            WHERE status = ? AND similarity_score >= ?
            ORDER BY similarity_score DESC
            LIMIT ?
        """
        rows = self.execute(sql, (status, threshold, limit))
        return [models.JobPosting(**dict(row)) for row in rows]

    def mark_postings_seen(self, posting_ids: list[int]) -> None:
        """Mark postings as seen (included in digest).

        Args:
            posting_ids: List of posting IDs to mark as seen.
        """
        if not posting_ids:
            return
        placeholders = ",".join("?" * len(posting_ids))
        sql = f"UPDATE job_postings SET status = 'seen' WHERE id IN ({placeholders})"
        self.execute(sql, tuple(posting_ids))

    def get_company_name(self, company_id: int) -> str | None:
        """Get company name by ID.

        Args:
            company_id: Company ID to look up.

        Returns:
            Company name or None if not found.
        """
        sql = "SELECT name FROM companies WHERE id = ?"
        rows = self.execute(sql, (company_id,))
        return rows[0]["name"] if rows else None

    def get_or_create_location(self, parsed) -> int:
        existing = self.execute(
            "SELECT id FROM locations WHERE canonical_name = ?",
            (parsed.canonical_name,),
        )
        if existing:
            return existing[0]["id"]

        sql = """
            INSERT INTO locations (canonical_name, city, state, state_code,
                country, country_code, region, latitude, longitude,
                resolution_status, raw_fragment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                sql,
                (
                    parsed.canonical_name,
                    parsed.city,
                    parsed.state,
                    parsed.state_code,
                    parsed.country,
                    parsed.country_code,
                    parsed.region,
                    parsed.latitude,
                    parsed.longitude,
                    parsed.resolution_status,
                    parsed.raw_fragment,
                ),
            )
            return cursor.lastrowid or 0

    def link_posting_location(self, posting_id: int, location_id: int) -> None:
        sql = "INSERT OR IGNORE INTO job_posting_locations (posting_id, location_id) VALUES (?, ?)"
        self.execute(sql, (posting_id, location_id))

    def get_postings_by_work_model(self, work_model: str) -> list:
        sql = "SELECT * FROM job_postings WHERE work_model = ?"
        rows = self.execute(sql, (work_model,))
        return [models.JobPosting(**dict(row)) for row in rows]

    def get_postings_by_location(self, canonical_name: str) -> list:
        sql = """
            SELECT j.* FROM job_postings j
            JOIN job_posting_locations jpl ON j.id = jpl.posting_id
            JOIN locations l ON jpl.location_id = l.id
            WHERE l.canonical_name = ?
        """
        rows = self.execute(sql, (canonical_name,))
        return [models.JobPosting(**dict(row)) for row in rows]

    def get_postings_by_region(self, region: str) -> list:
        sql = """
            SELECT DISTINCT j.* FROM job_postings j
            JOIN job_posting_locations jpl ON j.id = jpl.posting_id
            JOIN locations l ON jpl.location_id = l.id
            WHERE l.region = ?
        """
        rows = self.execute(sql, (region,))
        return [models.JobPosting(**dict(row)) for row in rows]

    def get_postings_for_search(
        self, status: str | None = None
    ) -> list[tuple[models.JobPosting, str]]:
        """Get all postings with embeddings, joined with company name.

        Args:
            status: If set, filter by posting status.

        Returns:
            List of (JobPosting, company_name) tuples for postings that have
            embeddings stored.
        """
        sql = """
            SELECT p.*, c.name as company_name
            FROM job_postings p
            JOIN companies c ON p.company_id = c.id
            WHERE p.embedding IS NOT NULL
        """
        params: tuple = ()
        if status:
            sql += " AND p.status = ?"
            params = (status,)
        rows = self.execute(sql, params)
        results = []
        for row in rows:
            row_dict = dict(row)
            company_name = row_dict.pop("company_name")
            posting = models.JobPosting(**row_dict)
            results.append((posting, company_name))
        return results

    def get_posting_by_id(self, posting_id: int) -> models.JobPosting | None:
        sql = "SELECT * FROM job_postings WHERE id = ?"
        rows = self.execute(sql, (posting_id,))
        if rows:
            return models.JobPosting(**dict(rows[0]))
        return None

    def update_posting_status(self, posting_id: int, status: str) -> None:
        sql = "UPDATE job_postings SET status = ? WHERE id = ?"
        self.execute(sql, (status, posting_id))

    def count_postings(self, status: str | None = None) -> int:
        if status:
            sql = "SELECT COUNT(*) as cnt FROM job_postings WHERE status = ?"
            rows = self.execute(sql, (status,))
        else:
            sql = "SELECT COUNT(*) as cnt FROM job_postings"
            rows = self.execute(sql)
        return rows[0]["cnt"] if rows else 0

    def get_postings_paginated(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        threshold: float | None = None,
    ) -> list[tuple[models.JobPosting, str]]:
        sql = """
            SELECT p.*, c.name as company_name
            FROM job_postings p
            JOIN companies c ON p.company_id = c.id
        """
        params: list = []
        conditions: list[str] = []
        if status:
            conditions.append("p.status = ?")
            params.append(status)
        if threshold is not None:
            conditions.append("p.similarity_score >= ?")
            params.append(threshold)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY p.similarity_score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = self.execute(sql, tuple(params))
        results = []
        for row in rows:
            row_dict = dict(row)
            company_name = row_dict.pop("company_name")
            posting = models.JobPosting(**row_dict)
            results.append((posting, company_name))
        return results

    def get_labels_for_posting(self, posting_id: int) -> list[models.Label]:
        sql = "SELECT * FROM labels WHERE posting_id = ? ORDER BY labeled_at DESC"
        rows = self.execute(sql, (posting_id,))
        return [models.Label(**dict(row)) for row in rows]

    def get_agent_actions(self, limit: int = 50) -> list[models.AgentAction]:
        sql = "SELECT * FROM agent_actions ORDER BY created_at DESC LIMIT ?"
        rows = self.execute(sql, (limit,))
        return [models.AgentAction(**dict(row)) for row in rows]

    def get_setting(self, key: str) -> str | None:
        sql = "SELECT value FROM settings WHERE key = ?"
        rows = self.execute(sql, (key,))
        return rows[0]["value"] if rows else None

    def set_setting(self, key: str, value: str) -> None:
        sql = """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
        """
        self.execute(sql, (key, value, value))


def init_db(db_path: str | Path) -> Database:
    """Initialize database with schema."""
    db_path = Path(db_path)
    db = Database(db_path)

    with db.get_connection() as conn:
        conn.executescript(SCHEMA_SQL)

    db.migrate_resolve_columns()

    return db


def get_db() -> Database:
    """Get database instance from config."""
    from quarry.config import settings

    return Database(settings.db_path)
