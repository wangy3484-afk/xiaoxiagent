"""Produce a stable inventory and verify every retained exported artifact."""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from ops_agent.artifacts.storage import ArtifactCorruptedError, LocalArtifactStorage
from ops_agent.config import Settings
from ops_agent.persistence.repositories import AuthorizationSubject

_TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "users": ("id",),
    "sessions": ("id",),
    "idempotency_records": ("id",),
    "operations_briefs": ("id",),
    "brief_revisions": ("id",),
    "report_jobs": ("id",),
    "job_events": ("id",),
    "evidence_records": ("id",),
    "claims": ("id",),
    "claim_evidence_links": ("claim_id", "evidence_id"),
    "report_versions": ("id",),
    "quality_reviews": ("id",),
    "export_files": ("id",),
}


async def build_backup_inventory(settings: Settings) -> dict[str, Any]:
    """Hash the full business rows and check database/file integrity."""
    database_url = settings.database_url.get_secret_value().replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
    connection = await asyncpg.connect(database_url)
    try:
        tables: dict[str, dict[str, str | int]] = {}
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            for table, keys in _TABLE_KEYS.items():
                digest = hashlib.sha256()
                count = 0
                order = ", ".join(f'"{key}"' for key in keys)
                query = f'SELECT * FROM "{table}" ORDER BY {order}'
                async for row in connection.cursor(query, prefetch=100):
                    encoded = json.dumps(
                        dict(row),
                        default=str,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    digest.update(len(encoded).to_bytes(8, "big"))
                    digest.update(encoded)
                    count += 1
                tables[table] = {"count": count, "sha256": digest.hexdigest()}

            export_rows = await connection.fetch(
                """SELECT storage_key, owner_id, checksum_sha256, size_bytes
                   FROM export_files WHERE deleted_at IS NULL ORDER BY id"""
            )

        storage = LocalArtifactStorage(Path(settings.artifact_storage_path))
        exports: list[dict[str, str | int]] = []
        for row in export_rows:
            metadata, _ = storage.read(
                AuthorizationSubject(user_id=row["owner_id"]), row["storage_key"]
            )
            if (
                metadata.checksum_sha256 != row["checksum_sha256"]
                or metadata.size_bytes != row["size_bytes"]
            ):
                raise ArtifactCorruptedError(row["storage_key"])
            exports.append(
                {
                    "storage_key": row["storage_key"],
                    "checksum_sha256": row["checksum_sha256"],
                    "size_bytes": row["size_bytes"],
                }
            )

        return {"format_version": 1, "tables": tables, "exports": exports}
    finally:
        await connection.close()


def main() -> None:
    inventory = asyncio.run(build_backup_inventory(Settings()))
    print(json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
