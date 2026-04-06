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
                active, crawl_priority, notes, added_by, added_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    company.active,
                    company.crawl_priority,
                    company.notes,
                    company.added_by,
                    company.added_reason,
                ),
            )
            return cursor.lastrowid

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

    def update_company(self, company: models.Company) -> None:
        sql = """
            UPDATE companies SET name=?, domain=?, careers_url=?, ats_type=?,
                ats_slug=?, active=?, crawl_priority=?, notes=?, updated_at=CURRENT_TIMESTAMP
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
                company.active,
                company.crawl_priority,
                company.notes,
                company.id,
            ),
        )

    def insert_posting(self, posting: models.JobPosting) -> int:
        sql = """
            INSERT INTO job_postings (company_id, title, title_hash, url, description,
                location, remote, posted_at, source_id, source_type, similarity_score,
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
                    posting.remote,
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
            return cursor.lastrowid

    def posting_exists(self, company_id: int, title_hash: str) -> bool:
        sql = "SELECT 1 FROM job_postings WHERE company_id = ? AND title_hash = ?"
        rows = self.execute(sql, (company_id, title_hash))
        return len(rows) > 0

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
            return cursor.lastrowid

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
            return cursor.lastrowid

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
            return cursor.lastrowid

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
            return cursor.lastrowid

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

    return db


def get_db() -> Database:
    """Get database instance from config."""
    from quarry.config import settings

    return Database(settings.db_path)
