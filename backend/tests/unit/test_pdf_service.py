"""Unit tests for the lazy, atomically writing PDF service.

None of these tests need the native Pango/HarfBuzz libraries: WeasyPrint is
either simulated as unavailable or replaced by a fake module.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType

import pytest

from backend.app.core.config import settings
from backend.app.services import pdf_service as pdf_service_module
from backend.app.services.pdf_service import PDFRenderingUnavailable, PDFService

TEMPLATE_NAME = "pdf/invoice.html"
OUTPUT_NAME = "invoice_ORD-TEST.pdf"
CONTEXT = {"order": {"order_number": "ORD-TEST"}}


class _FakeTemplate:
    def render(self, context):
        return f"<html><body>{context}</body></html>"


class _FakeTemplateRenderer:
    def get_template(self, name):
        return _FakeTemplate()


def _make_fake_weasyprint(write_pdf) -> ModuleType:
    """A stand-in `weasyprint` module whose HTML.write_pdf is `write_pdf`."""
    module = ModuleType("weasyprint")

    class HTML:
        def __init__(self, string, base_url=None):
            self.string = string
            self.base_url = base_url

        def write_pdf(self, target):
            write_pdf(self, target)

    module.HTML = HTML  # type: ignore[attr-defined]
    return module


class _RaisingFinder:
    """A meta path finder that fails the import of `weasyprint` itself."""

    def __init__(self, error: BaseException):
        self.error = error

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "weasyprint":
            raise self.error
        # Any other module: defer to the finders behind this one.


def leftover_temp_files(directory: Path) -> list[str]:
    """Leftover temporary files, including the hidden ones this service writes.

    `glob.glob(f'{directory}/*.tmp')` would skip names starting with a dot and
    make every assertion below pass vacuously.
    """
    return [name for name in os.listdir(directory) if name.endswith(".tmp")]


@pytest.fixture(autouse=True)
def clear_loader_memo():
    """Forget a memoized loader result before and after every test."""
    pdf_service_module._load_weasyprint.cache_clear()
    yield
    pdf_service_module._load_weasyprint.cache_clear()


@pytest.fixture
def service(tmp_path, monkeypatch) -> PDFService:
    monkeypatch.setattr(settings, "pdf_output_dir", str(tmp_path))
    return PDFService(_FakeTemplateRenderer())


def render(service: PDFService, output_name: str = OUTPUT_NAME) -> Path:
    return asyncio.run(service.render_pdf(TEMPLATE_NAME, CONTEXT, output_name))


def warnings_of(caplog) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno == logging.WARNING]


def test_import_error_marks_rendering_unavailable_and_warns_once(service, tmp_path, monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "weasyprint", None)

    with caplog.at_level(logging.WARNING, logger=pdf_service_module.__name__):
        for _ in range(2):
            with pytest.raises(PDFRenderingUnavailable):
                render(service)

    assert pdf_service_module.pdf_rendering_available() is False
    assert len(warnings_of(caplog)) == 1
    assert "unavailable" in warnings_of(caplog)[0].getMessage()
    assert list(tmp_path.iterdir()) == []


def test_os_error_marks_rendering_unavailable_and_warns_once(service, tmp_path, monkeypatch, caplog):
    error = OSError("cannot load library 'libpango-1.0-0'")
    monkeypatch.delitem(sys.modules, "weasyprint", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_RaisingFinder(error), *sys.meta_path])

    with caplog.at_level(logging.WARNING, logger=pdf_service_module.__name__):
        for _ in range(2):
            with pytest.raises(PDFRenderingUnavailable):
                render(service)

    assert pdf_service_module.pdf_rendering_available() is False
    assert len(warnings_of(caplog)) == 1
    assert "libpango-1.0-0" in warnings_of(caplog)[0].getMessage()
    assert list(tmp_path.iterdir()) == []


def test_rendering_error_propagates_and_leaves_no_files(service, tmp_path, monkeypatch):
    def write_pdf(html, written_to):
        # Write a partial document first, so the cleanup really has work to do.
        Path(written_to).write_bytes(b"%PDF-part")
        raise ValueError("broken template")

    monkeypatch.setitem(sys.modules, "weasyprint", _make_fake_weasyprint(write_pdf))

    with pytest.raises(ValueError, match="broken template"):
        render(service)

    assert not (tmp_path / OUTPUT_NAME).exists()
    assert leftover_temp_files(tmp_path) == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_goes_to_a_temporary_file_and_is_moved_onto_the_target(service, tmp_path, monkeypatch):
    target = tmp_path / OUTPUT_NAME

    def write_pdf(html, written_to):
        written_path = Path(written_to)
        assert written_path.suffix == ".tmp"
        assert written_path.parent == tmp_path
        assert written_path.name.startswith(f".{OUTPUT_NAME}.")
        assert not target.exists(), "the target must not appear before the write completes"
        written_path.write_bytes(b"%PDF-fake")

    monkeypatch.setitem(sys.modules, "weasyprint", _make_fake_weasyprint(write_pdf))

    result = render(service)

    assert result == target
    assert target.read_bytes() == b"%PDF-fake"
    assert leftover_temp_files(tmp_path) == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_concurrent_renders_leave_one_complete_document(service, tmp_path, monkeypatch):
    # Each render writes a body of its own, so a mixture of the two is detectable.
    fillers = iter((b"a", b"b"))
    bodies: list[bytes] = []
    lock = threading.Lock()

    def write_pdf(html, written_to):
        with lock:
            body = b"%PDF-" + next(fillers) * 64
            bodies.append(body)
        with Path(written_to).open("wb") as handle:
            handle.write(body[:5])
            handle.flush()
            time.sleep(0.05)
            handle.write(body[5:])

    monkeypatch.setitem(sys.modules, "weasyprint", _make_fake_weasyprint(write_pdf))

    errors: list[BaseException] = []

    def worker():
        try:
            render(service)
        except BaseException as exc:  # noqa: BLE001 - reported by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, name=name) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(bodies) == 2
    assert (tmp_path / OUTPUT_NAME).read_bytes() in set(bodies)
    assert leftover_temp_files(tmp_path) == []
    assert list(tmp_path.glob("*.tmp")) == []
    assert os.listdir(tmp_path) == [OUTPUT_NAME]
