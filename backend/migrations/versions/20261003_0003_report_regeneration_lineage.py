"""Track the source report version for regeneration jobs.

Revision ID: 20261003_0003
Revises: 20260930_0002
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_0003"
down_revision: str | None = "20260930_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("report_jobs") as batch_op:
        batch_op.add_column(
            sa.Column("source_report_version_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_index(
            "ix_report_jobs_source_report_version_id",
            ["source_report_version_id"],
        )
        batch_op.create_foreign_key(
            "fk_report_jobs_source_report_version",
            "report_versions",
            ["source_report_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("report_jobs") as batch_op:
        batch_op.drop_constraint(
            "fk_report_jobs_source_report_version",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_report_jobs_source_report_version_id")
        batch_op.drop_column("source_report_version_id")
