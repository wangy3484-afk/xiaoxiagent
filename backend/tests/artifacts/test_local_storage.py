"""Local artifact storage contract tests."""

import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from ops_agent.artifacts import (
    ArtifactAlreadyExistsError,
    ArtifactCorruptedError,
    ArtifactNotFoundError,
    InvalidStorageKeyError,
    LocalArtifactStorage,
)
from ops_agent.persistence.repositories import AuthorizationSubject


@pytest.fixture
def storage_root() -> Iterator[Path]:
    workspace = Path.cwd().resolve()
    root = (workspace / ".test-artifacts" / f"artifact-storage-{uuid4()}").resolve()
    root.relative_to(workspace)
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        shutil.rmtree(root)


def test_write_read_and_persisted_metadata(storage_root: Path) -> None:
    owner = AuthorizationSubject(user_id="owner-a")
    storage = LocalArtifactStorage(storage_root)
    content = "专业运营报告".encode()

    metadata = storage.write(
        owner,
        "reports/report-v1.md",
        content,
        content_type="text/markdown; charset=utf-8",
    )
    reloaded_metadata, reloaded_content = LocalArtifactStorage(storage_root).read(
        owner,
        metadata.storage_key,
    )

    assert reloaded_content == content
    assert reloaded_metadata == metadata
    assert metadata.size_bytes == len(content)
    assert metadata.checksum_sha256 == hashlib.sha256(content).hexdigest()

    with pytest.raises(ArtifactAlreadyExistsError):
        storage.write(
            owner,
            metadata.storage_key,
            b"replacement",
            content_type="text/plain",
        )


def test_cross_user_read_and_delete_do_not_reveal_artifact(storage_root: Path) -> None:
    owner = AuthorizationSubject(user_id="owner-a")
    stranger = AuthorizationSubject(user_id="owner-b")
    storage = LocalArtifactStorage(storage_root)
    storage.write(owner, "reports/private.pdf", b"private", content_type="application/pdf")

    with pytest.raises(ArtifactNotFoundError):
        storage.read(stranger, "reports/private.pdf")
    with pytest.raises(ArtifactNotFoundError):
        storage.delete(stranger, "reports/private.pdf")

    assert storage.read(owner, "reports/private.pdf")[1] == b"private"


def test_corruption_is_detected_before_bytes_are_returned(storage_root: Path) -> None:
    owner = AuthorizationSubject(user_id="owner-a")
    storage = LocalArtifactStorage(storage_root)
    storage.write(owner, "reports/report.md", b"original", content_type="text/markdown")
    (storage_root / "data" / "reports" / "report.md").write_bytes(b"tampered")

    with pytest.raises(ArtifactCorruptedError):
        storage.read(owner, "reports/report.md")


def test_delete_removes_artifact_and_metadata(storage_root: Path) -> None:
    owner = AuthorizationSubject(user_id="owner-a")
    storage = LocalArtifactStorage(storage_root)
    storage.write(owner, "reports/report.md", b"content", content_type="text/markdown")

    storage.delete(owner, "reports/report.md")

    with pytest.raises(ArtifactNotFoundError):
        storage.read(owner, "reports/report.md")


@pytest.mark.parametrize(
    "storage_key",
    [
        "",
        ".",
        "..",
        "../secret",
        "/absolute",
        "nested/../../secret",
        "nested\\..\\secret",
        "C:/secret",
    ],
)
def test_path_traversal_and_ambiguous_keys_are_rejected(
    storage_root: Path,
    storage_key: str,
) -> None:
    storage = LocalArtifactStorage(storage_root)
    owner = AuthorizationSubject(user_id="owner-a")

    with pytest.raises(InvalidStorageKeyError):
        storage.write(owner, storage_key, b"data", content_type="application/octet-stream")
