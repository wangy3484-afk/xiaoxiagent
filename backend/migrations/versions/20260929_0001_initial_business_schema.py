"""Create the initial business schema.

Revision ID: 20260929_0001
Revises: None
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "operations_briefs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("latest_revision_number", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operations_briefs_owner_id", "operations_briefs", ["owner_id"])
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_user_expires", "sessions", ["user_id", "expires_at"])
    op.create_table(
        "brief_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("brief_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("brief_payload", sa.JSON(), nullable=False),
        sa.Column("classification_payload", sa.JSON(), nullable=False),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brief_id"], ["operations_briefs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brief_id", "revision_number", name="uq_brief_revision"),
    )
    op.create_index("ix_brief_revisions_brief_id", "brief_revisions", ["brief_id"])
    op.create_index("ix_brief_revisions_owner_id", "brief_revisions", ["owner_id"])
    op.create_table(
        "report_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("brief_id", sa.String(length=36), nullable=False),
        sa.Column("brief_revision_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["brief_id"], ["operations_briefs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["brief_revision_id"], ["brief_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_job_owner_idempotency"),
    )
    op.create_index("ix_report_jobs_owner_id", "report_jobs", ["owner_id"])
    op.create_index("ix_report_jobs_owner_created", "report_jobs", ["owner_id", "created_at"])
    op.create_table(
        "job_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("retention_locked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["report_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "sequence", name="uq_job_event_sequence"),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])
    op.create_index("ix_job_events_created", "job_events", ["created_at"])
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_url", sa.String(length=2048), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("publisher", sa.String(length=300), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("publication_date_unknown", sa.Boolean(), nullable=False),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supporting_excerpt", sa.Text(), nullable=False),
        sa.Column("context_summary", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("credibility_payload", sa.JSON(), nullable=False),
        sa.Column("adaptation_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["report_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "normalized_url", name="uq_job_evidence_url"),
    )
    op.create_index("ix_evidence_records_job_id", "evidence_records", ["job_id"])
    op.create_index("ix_evidence_records_owner_id", "evidence_records", ["owner_id"])
    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(length=40), nullable=False),
        sa.Column("verification_status", sa.String(length=40), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["report_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claims_job_id", "claims", ["job_id"])
    op.create_index("ix_claims_owner_id", "claims", ["owner_id"])
    op.create_table(
        "claim_evidence_links",
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("support_type", sa.String(length=40), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["evidence_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("claim_id", "evidence_id"),
    )
    op.create_table(
        "report_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("brief_revision_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("delivery_status", sa.String(length=40), nullable=False),
        sa.Column("report_payload", sa.JSON(), nullable=False),
        sa.Column("playbook_versions", sa.JSON(), nullable=False),
        sa.Column("model_configuration", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brief_revision_id"], ["brief_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["report_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "version_number", name="uq_report_job_version"),
    )
    op.create_index("ix_report_versions_job_id", "report_versions", ["job_id"])
    op.create_index("ix_report_versions_owner_id", "report_versions", ["owner_id"])
    op.create_index(
        "ix_report_versions_owner_generated", "report_versions", ["owner_id", "generated_at"]
    )
    op.create_table(
        "quality_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("report_version_id", sa.String(length=36), nullable=False),
        sa.Column("revision_round", sa.Integer(), nullable=False),
        sa.Column("review_payload", sa.JSON(), nullable=False),
        sa.Column("blocking_issue_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["report_version_id"], ["report_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "report_version_id", "revision_round", name="uq_quality_review_round"
        ),
    )
    op.create_index("ix_quality_reviews_owner_id", "quality_reviews", ["owner_id"])
    op.create_index(
        "ix_quality_reviews_report_version_id", "quality_reviews", ["report_version_id"]
    )
    op.create_table(
        "export_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("report_version_id", sa.String(length=36), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("storage_key", sa.String(length=1000), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=False),
        sa.Column("is_temporary", sa.Boolean(), nullable=False),
        sa.Column("retention_locked", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["report_version_id"], ["report_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_export_files_owner_id", "export_files", ["owner_id"])
    op.create_index(
        "ix_export_files_report_version_id", "export_files", ["report_version_id"]
    )
    op.create_index(
        "ix_export_files_expiry", "export_files", ["is_temporary", "expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_export_files_expiry", table_name="export_files")
    op.drop_index("ix_export_files_report_version_id", table_name="export_files")
    op.drop_index("ix_export_files_owner_id", table_name="export_files")
    op.drop_table("export_files")
    op.drop_index("ix_quality_reviews_report_version_id", table_name="quality_reviews")
    op.drop_index("ix_quality_reviews_owner_id", table_name="quality_reviews")
    op.drop_table("quality_reviews")
    op.drop_index("ix_report_versions_owner_generated", table_name="report_versions")
    op.drop_index("ix_report_versions_owner_id", table_name="report_versions")
    op.drop_index("ix_report_versions_job_id", table_name="report_versions")
    op.drop_table("report_versions")
    op.drop_table("claim_evidence_links")
    op.drop_index("ix_claims_owner_id", table_name="claims")
    op.drop_index("ix_claims_job_id", table_name="claims")
    op.drop_table("claims")
    op.drop_index("ix_evidence_records_owner_id", table_name="evidence_records")
    op.drop_index("ix_evidence_records_job_id", table_name="evidence_records")
    op.drop_table("evidence_records")
    op.drop_index("ix_job_events_created", table_name="job_events")
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_report_jobs_owner_created", table_name="report_jobs")
    op.drop_index("ix_report_jobs_owner_id", table_name="report_jobs")
    op.drop_table("report_jobs")
    op.drop_index("ix_brief_revisions_owner_id", table_name="brief_revisions")
    op.drop_index("ix_brief_revisions_brief_id", table_name="brief_revisions")
    op.drop_table("brief_revisions")
    op.drop_index("ix_sessions_user_expires", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_operations_briefs_owner_id", table_name="operations_briefs")
    op.drop_table("operations_briefs")
    op.drop_table("users")
