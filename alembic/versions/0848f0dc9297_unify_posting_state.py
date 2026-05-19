"""unify_posting_state

Revision ID: 0848f0dc9297
Revises: a09b5faf35b6
Create Date: 2026-05-18 11:06:32.471319

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0848f0dc9297"
down_revision: Union[str, Sequence[str], None] = "a09b5faf35b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_posting_state",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("posting_id", sa.Integer(), nullable=False),
        sa.Column("interest", sa.Boolean(), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("labeled_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["posting_id"], ["job_postings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "posting_id"),
    )
    op.create_index("idx_state_user", "user_posting_state", ["user_id"])
    op.create_index("idx_state_posting", "user_posting_state", ["posting_id"])
    op.create_index("idx_state_interest", "user_posting_state", ["user_id", "interest"])
    # Drop old tables. No data migrated — existing labels (including
    # auto-derived signals like seen→negative) are considered untrusted.
    op.drop_table("user_labels")
    op.drop_table("user_posting_status")


def downgrade() -> None:
    """Downgrade schema."""
    # Recreate user_labels
    op.create_table(
        "user_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("posting_id", sa.Integer(), nullable=False),
        sa.Column("signal", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "labeled_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "label_source",
            sa.Text(),
            server_default=sa.text("'user'"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "signal IN ('positive','negative','applied','skip')",
            name="ck_user_labels_signal",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["posting_id"], ["job_postings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "posting_id", "signal"),
    )
    op.create_index("idx_labels_user", "user_labels", ["user_id"])
    op.create_index("idx_labels_posting", "user_labels", ["posting_id"])

    # Recreate user_posting_status
    op.create_table(
        "user_posting_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("posting_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'new'"), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('new','seen','applied','rejected','archived')",
            name="ck_posting_status_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["posting_id"], ["job_postings.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "posting_id"),
    )
    op.create_index("idx_posting_status_user", "user_posting_status", ["user_id"])
    op.create_index("idx_posting_status_posting", "user_posting_status", ["posting_id"])
    op.create_index(
        "idx_posting_status_status", "user_posting_status", ["user_id", "status"]
    )

    op.drop_index("idx_state_interest", table_name="user_posting_state")
    op.drop_index("idx_state_posting", table_name="user_posting_state")
    op.drop_index("idx_state_user", table_name="user_posting_state")
    op.drop_table("user_posting_state")
