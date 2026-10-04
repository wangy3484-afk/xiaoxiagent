"""Presentation-only branding configuration shared by report renderers."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path


class BrandAssetError(ValueError):
    """Raised when a configured brand asset cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class ReportBranding:
    """Brand identity that must not alter the report's business content."""

    title: str | None = None
    header_text: str | None = None
    logo_path: Path | None = None
    logo_alt: str = "品牌 Logo"

    def display_title(self, report_title: str) -> str:
        return f"{self.title}｜{report_title}" if self.title else report_title

    def logo_data_uri(self) -> str | None:
        if self.logo_path is None:
            return None
        path = self.logo_path.resolve()
        mime_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(path.suffix.lower())
        if mime_type is None:
            raise BrandAssetError("brand logo must be a PNG or JPEG image")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise BrandAssetError("configured brand logo cannot be read") from exc
        if not content:
            raise BrandAssetError("configured brand logo is empty")
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"
