"""No static image may be heavy again, or lie about its format (change fix-oversized-images).

Every file in ``static/img/`` was once 3.16 MB, and the twelve ``*.jpg``
product photos held PNG data while the pages announced them as
``type="image/jpeg"``. Browsers sniff the bytes, so nothing ever failed. These
tests fail instead, on the weight and on the mismatch, for whatever the
directory holds - not for a fixed list of names, so a new product photo is
weighed on the commit that adds it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

IMG_DIR = Path(__file__).resolve().parents[2] / "app" / "static" / "img"

#: Comfortably above the 167 KB largest product image, far below the 3.16 MB
#: that made the early load test measure the network instead of the shop.
MAX_FILE_BYTES = 400 * 1024

#: The whole directory, which the container image carries in every pull.
MAX_DIR_BYTES = 1_500 * 1024

#: The first bytes of each format the shop serves, which is what a browser
#: sniffs and what the extension is supposed to promise.
SIGNATURES: dict[str, bytes] = {
    "JPEG": b"\xff\xd8\xff",
    "PNG": b"\x89PNG\r\n\x1a\n",
    "GIF": b"GIF8",
    "WEBP": b"RIFF",
}

#: What each extension must contain.
EXTENSION_FORMAT = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}


def actual_format(data: bytes) -> str | None:
    """The format of ``data`` from its magic bytes, or ``None`` if unknown."""
    for name, signature in SIGNATURES.items():
        if data.startswith(signature):
            return name
    return None


def image_files() -> list[Path]:
    return sorted(path for path in IMG_DIR.iterdir() if path.is_file())


def test_the_directory_is_not_empty() -> None:
    """Guards the parametrised tests below, which would vacuously pass."""
    assert len(image_files()) >= 14


@pytest.mark.parametrize("path", image_files(), ids=lambda path: path.name)
def test_image_stays_within_its_budget(path: Path) -> None:
    size = path.stat().st_size
    assert size <= MAX_FILE_BYTES, (
        f"{path.name} is {size / 1024:.0f} KB, over the {MAX_FILE_BYTES / 1024:.0f} KB budget; "
        "re-encode it (JPEG quality 82 for photos) rather than raising the budget"
    )


@pytest.mark.parametrize("path", image_files(), ids=lambda path: path.name)
def test_image_content_matches_its_extension(path: Path) -> None:
    expected = EXTENSION_FORMAT.get(path.suffix.lower())
    assert expected, f"{path.name} has an extension this budget does not cover"
    found = actual_format(path.read_bytes()[:16])
    assert found == expected, (
        f"{path.name} contains {found or 'unrecognised'} data but is named {path.suffix}; "
        "the pages declare type=\"image/jpeg\" for these files"
    )


def test_the_whole_directory_stays_small() -> None:
    total = sum(path.stat().st_size for path in image_files())
    assert total <= MAX_DIR_BYTES, (
        f"static/img/ is {total / 1024 / 1024:.1f} MB, over the "
        f"{MAX_DIR_BYTES / 1024 / 1024:.1f} MB budget"
    )


# The guard's own tests: the checks above are only worth having if they fail.


def test_a_heavy_file_is_over_the_budget() -> None:
    assert 3_163_292 > MAX_FILE_BYTES


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"\xff\xd8\xff\xe0" + b"\x00" * 12, "JPEG"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "PNG"),
        (b"not an image at all", None),
    ],
)
def test_format_is_read_from_the_magic_bytes(data: bytes, expected: str | None) -> None:
    assert actual_format(data) == expected


def test_png_data_under_a_jpg_name_is_a_mismatch() -> None:
    """The exact mistake this change corrects."""
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    assert actual_format(png_bytes) != EXTENSION_FORMAT[".jpg"]
