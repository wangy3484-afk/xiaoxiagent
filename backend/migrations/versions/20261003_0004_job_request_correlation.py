"""Persist the API request correlation identifier on report jobs.

Revision ID: 20261003_0004
Revises: 20261003_0003
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_0004"
down_revision: str | None = "20261003_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("report_jobs") as batch_op:
        batch_op.add_column(sa.Column("request_id", sa.String(length=100), nullable=True))
        batch_op.create_index("ix_report_jobs_request_id", ["request_id"])


def downgrade() -> None:
    with op.batch_alter_table("report_jobs") as batch_op:
        batch_op.drop_index("ix_report_jobs_request_id")
        batch_op.drop_column("request_id")
