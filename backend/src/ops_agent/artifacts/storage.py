"""Authorized artifact storage with checksum verification."""

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Protocol

from ops_agent.persistence.repositories import AuthorizationSubject


class ArtifactStorageError(Exception):
    """Base class for stable artifact storage failures."""


class InvalidStorageKeyError(ArtifactStorageError):
    """Raised before a key can escape or ambiguously address the storage root."""


class ArtifactNotFoundError(ArtifactStorageError):
    """Used for both missing and unauthorized artifacts to avoid existence leaks."""


class ArtifactAlreadyExistsError(ArtifactStorageError):
    """Raised instead of silently replacing an immutable artifact."""


class ArtifactCorruptedError(ArtifactStorageError):
    """Raised when bytes no longer match their recorded checksum or size."""


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    storage_key: str
    owner_id: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    created_at: datetime


class ArtifactStorage(Protocol):
    """Storage boundary shared by local-volume and future object-store adapters."""

    def write(
        self,
        subject: AuthorizationSubject,
        storage_key: str,
        content: bytes,
        *,
        content_type: str,
    ) -> ArtifactMetadata: ...

    def read(
        self,
        subject: AuthorizationSubject,
        storage_key: str,
    ) -> tuple[ArtifactMetadata, bytes]: ...

    def delete(self, subject: AuthorizationSubject, storage_key: str) -> None: ...


class LocalArtifactStorage:
    """Store artifacts and metadata beneath a mounted local directory."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._data_root = self._root / "data"
        self._metadata_root = self._root / "metadata"
        self._data_root.mkdir(parents=True, exist_ok=True)
        self._metadata_root.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        subject: AuthorizationSubject,
        storage_key: str,
        content: bytes,
        *,
        content_type: str,
    ) -> ArtifactMetadata:
        target = self._artifact_path(storage_key)
        metadata_path = self._metadata_path(storage_key)
        if target.exists() or metadata_path.exists():
            existing = self._load_metadata(storage_key)
            if existing.owner_id != subject.user_id:
                raise ArtifactNotFoundError(storage_key)
            raise ArtifactAlreadyExistsError(storage_key)

        metadata = ArtifactMetadata(
            storage_key=storage_key,
            owner_id=subject.user_id,
            content_type=content_type,
            size_bytes=len(content),
            checksum_sha256=hashlib.sha256(content).hexdigest(),
            created_at=datetime.now(UTC),
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(target, content)
        try:
            self._atomic_write(
                metadata_path,
                json.dumps(
                    {
                        **asdict(metadata),
                        "created_at": metadata.created_at.isoformat(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8"),
            )
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return metadata

    def read(
        self,
        subject: AuthorizationSubject,
        storage_key: str,
    ) -> tuple[ArtifactMetadata, bytes]:
        target = self._artifact_path(storage_key)
        metadata = self._authorized_metadata(subject, storage_key)
        try:
            content = target.read_bytes()
        except FileNotFoundError as error:
            raise ArtifactCorruptedError(storage_key) from error

        checksum = hashlib.sha256(content).hexdigest()
        if len(content) != metadata.size_bytes or checksum != metadata.checksum_sha256:
            raise ArtifactCorruptedError(storage_key)
        return metadata, content

    def delete(self, subject: AuthorizationSubject, storage_key: str) -> None:
        target = self._artifact_path(storage_key)
        metadata_path = self._metadata_path(storage_key)
        self._authorized_metadata(subject, storage_key)
        target.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        self._remove_empty_parents(target.parent)

    def _authorized_metadata(
        self,
        subject: AuthorizationSubject,
        storage_key: str,
    ) -> ArtifactMetadata:
        metadata = self._load_metadata(storage_key)
        if metadata.owner_id != subject.user_id:
            raise ArtifactNotFoundError(storage_key)
        return metadata

    def _load_metadata(self, storage_key: str) -> ArtifactMetadata:
        metadata_path = self._metadata_path(storage_key)
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            return ArtifactMetadata(
                storage_key=str(payload["storage_key"]),
                owner_id=str(payload["owner_id"]),
                content_type=str(payload["content_type"]),
                size_bytes=int(payload["size_bytes"]),
                checksum_sha256=str(payload["checksum_sha256"]),
                created_at=datetime.fromisoformat(str(payload["created_at"])),
            )
        except FileNotFoundError as error:
            raise ArtifactNotFoundError(storage_key) from error
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ArtifactCorruptedError(storage_key) from error

    def _artifact_path(self, storage_key: str) -> Path:
        parts = self._validated_parts(storage_key)
        target = self._data_root.joinpath(*parts).resolve()
        try:
            target.relative_to(self._data_root)
        except ValueError as error:
            raise InvalidStorageKeyError(storage_key) from error
        return target

    def _metadata_path(self, storage_key: str) -> Path:
        self._validated_parts(storage_key)
        digest = hashlib.sha256(storage_key.encode("utf-8")).hexdigest()
        return self._metadata_root / digest[:2] / f"{digest}.json"

    @staticmethod
    def _validated_parts(storage_key: str) -> tuple[str, ...]:
        if not storage_key or "\\" in storage_key or ":" in storage_key:
            raise InvalidStorageKeyError(storage_key)
        pure_path = PurePosixPath(storage_key)
        if (
            not pure_path.parts
            or pure_path.is_absolute()
            or any(part in {"", ".", ".."} for part in pure_path.parts)
        ):
            raise InvalidStorageKeyError(storage_key)
        return pure_path.parts

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _remove_empty_parents(self, directory: Path) -> None:
        while directory != self._data_root:
            try:
                directory.rmdir()
            except OSError:
                return
            directory = directory.parent
