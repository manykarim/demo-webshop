from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Dict
from uuid import uuid4

from ..core.config import settings

logger = logging.getLogger(__name__)


class PDFRenderingUnavailable(RuntimeError):
    """Raised when a PDF is requested while WeasyPrint cannot be loaded.

    The Python package is always installed, but its native dependencies
    (Pango, HarfBuzz) are absent on many development machines. Importing
    WeasyPrint then fails with ``ImportError`` or, from cffi, ``OSError``.
    """


@lru_cache(maxsize=1)
def _load_weasyprint() -> ModuleType | None:
    """Import WeasyPrint on first use.

    Returns the module, or ``None`` when rendering is unavailable. The result is
    memoized, so the warning below is logged at most once per process. Call
    ``_load_weasyprint.cache_clear()`` to forget the result (tests only).
    """
    try:
        import weasyprint
    except (ImportError, OSError) as exc:
        logger.warning(
            "PDF rendering is unavailable in this environment: %s: %s",
            type(exc).__name__,
            exc,
        )
        return None
    return weasyprint


def pdf_rendering_available() -> bool:
    """Whether PDF rendering works here. Triggers the import on first call."""
    return _load_weasyprint() is not None


class PDFService:
    def __init__(self, template_renderer):
        self.templates = template_renderer
        self.output_dir = Path(settings.pdf_output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _render_pdf_sync(self, template_name: str, context: Dict[str, Any], output_name: str) -> Path:
        weasyprint = _load_weasyprint()
        if weasyprint is None:
            raise PDFRenderingUnavailable("PDF rendering is unavailable in this environment")

        html_content = self.templates.get_template(template_name).render(context)
        output_path = self.output_dir / output_name
        # Render into a unique hidden temporary file beside the target and move it
        # into place, so a document that exists is always complete.
        temp_path = self.output_dir / f".{output_name}.{uuid4().hex}.tmp"
        try:
            # The base_url is crucial for resolving relative paths for images, CSS, etc.
            # We point it to the 'backend' directory, which acts as the root for asset paths.
            weasyprint.HTML(string=html_content, base_url=str(settings.base_dir)).write_pdf(str(temp_path))
            os.replace(temp_path, output_path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
        return output_path

    async def render_pdf(self, template_name: str, context: Dict[str, Any], output_name: str) -> Path:
        if not pdf_rendering_available():
            raise PDFRenderingUnavailable("PDF rendering is unavailable in this environment")
        return await asyncio.to_thread(self._render_pdf_sync, template_name, context, output_name)
