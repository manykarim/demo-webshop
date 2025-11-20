from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

from weasyprint import HTML

from ..core.config import settings


class PDFService:
    def __init__(self, template_renderer):
        self.templates = template_renderer
        self.output_dir = Path(settings.pdf_output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _render_pdf_sync(self, template_name: str, context: Dict[str, Any], output_name: str) -> Path:
        html_content = self.templates.get_template(template_name).render(context)
        output_path = self.output_dir / output_name
        # The base_url is crucial for resolving relative paths for images, CSS, etc.
        # We point it to the 'backend' directory, which acts as the root for asset paths.
        HTML(string=html_content, base_url=str(settings.base_dir)).write_pdf(str(output_path))
        return output_path

    async def render_pdf(self, template_name: str, context: Dict[str, Any], output_name: str) -> Path:
        return await asyncio.to_thread(self._render_pdf_sync, template_name, context, output_name)
