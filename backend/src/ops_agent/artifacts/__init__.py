"""Artifact storage contracts and adapters."""

from ops_agent.artifacts.branding import BrandAssetError, ReportBranding
from ops_agent.artifacts.pdf_rendering import (
    PdfFontUnavailableError,
    PdfRenderConfig,
    render_operations_report_pdf,
)
from ops_agent.artifacts.rendering import (
    RenderedReport,
    render_operations_report,
    render_operations_report_html,
    render_operations_report_markdown,
    report_responsibility_notice,
)
from ops_agent.artifacts.storage import (
    ArtifactAlreadyExistsError,
    ArtifactCorruptedError,
    ArtifactMetadata,
    ArtifactNotFoundError,
    ArtifactStorage,
    InvalidStorageKeyError,
    LocalArtifactStorage,
)

__all__ = [
    "ArtifactAlreadyExistsError",
    "ArtifactCorruptedError",
    "ArtifactMetadata",
    "ArtifactNotFoundError",
    "ArtifactStorage",
    "InvalidStorageKeyError",
    "LocalArtifactStorage",
    "BrandAssetError",
    "PdfFontUnavailableError",
    "PdfRenderConfig",
    "RenderedReport",
    "ReportBranding",
    "report_responsibility_notice",
    "render_operations_report",
    "render_operations_report_html",
    "render_operations_report_markdown",
    "render_operations_report_pdf",
]
