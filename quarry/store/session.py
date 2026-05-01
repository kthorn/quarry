# quarry/store/session.py
"""SQLAlchemy engine and session management.

Provides:
- get_engine(): create or return the singleton SQLite engine
- get_session(): return a new Session bound to the engine
- session_scope(): context manager for transactional sessions
- PRAGMA foreign_keys = ON enforced on every connection
"""

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from quarry.store.models import _pragma_foreign_keys_on

_engines: dict[str, Engine] = {}
_SessionLocal: sessionmaker | None = None


def get_engine(db_path: str | Path | None = None) -> Engine:
    """Return (or create) a SQLAlchemy Engine for the given database path.

    Engines are cached per database URL so tests using tmp_path
    get isolated engines per test database. SQLite requires a single
    writer per database, so a singleton per URL is appropriate.

    Args:
        db_path: Path to SQLite database. Uses config if not provided.

    Returns:
        SQLAlchemy Engine configured for the project database.
    """
    global _SessionLocal

    if db_path is None:
        from quarry.config import settings

        db_path = settings.db_path

    db_url = f"sqlite:///{db_path}"

    if db_url not in _engines:
        engine = create_engine(
            db_url,
            echo=False,
        )
        event.listen(engine, "connect", _pragma_foreign_keys_on)
        _engines[db_url] = engine

    return _engines[db_url]


def get_session() -> Session:
    """Return a new SQLAlchemy Session bound to the current engine.

    The caller is responsible for closing the session.
    Prefer session_scope() for automatic cleanup.
    """
    global _SessionLocal
    engine = get_engine()
    # Recreate sessionmaker if engine changed (e.g., tests with different DBs)
    if _SessionLocal is None or _SessionLocal.kw["bind"] is not engine:
        _SessionLocal = sessionmaker(bind=engine)
    return _SessionLocal()


@contextmanager
def session_scope(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Context manager for transactional session scope.

    Commits on success, rolls back on exception.

    Usage:
        with session_scope() as session:
            session.add(Company(name="Acme"))

    Args:
        engine: If provided, uses this engine directly (e.g., for init_db
                against a custom path). If None, uses get_session() which
                binds to the default engine from config.
    """
    if engine is not None:
        session = Session(bind=engine)
    else:
        session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
