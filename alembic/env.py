# alembic/env.py
import os
import sys
from logging.config import fileConfig

# Ensure repo root is in sys.path so quarry imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, pool, text

from alembic import context

# Import our ORM models so Base.metadata is populated
from quarry.store.models import Base

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target_metadata to our ORM Base
target_metadata = Base.metadata


# Dynamically set sqlalchemy.url from project config
def get_url() -> str:
    from quarry.config import settings

    return f"sqlite:///{settings.db_path}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    # Build engine directly with the configured URL (do not use
    # engine_from_config + URL reassignment — Engine.url is immutable)
    connectable = create_engine(get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # Enforce foreign keys during migration operations
        connection.execute(text("PRAGMA foreign_keys = ON"))

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
