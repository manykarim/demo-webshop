"""Unit tests for tools/resolve_image_version.py (the CI ref -> APP_VERSION map)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.resolve_image_version import (
    DOCKER_TAG_MAX_LENGTH,
    InvalidWorkshopTag,
    main,
    resolve_version,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "resolve_image_version.py"

TOO_LONG_WORKSHOP_TAG = "workshop-" + "a" * (129 - len("workshop-"))


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("refs/tags/workshop-2026-10", "workshop-2026-10"),
        ("refs/tags/v0.2.0", "0.2.0"),
        ("refs/heads/main", "dev"),
        ("refs/heads/feature-x", "dev"),
        ("refs/pull/7/merge", "dev"),
    ],
)
def test_resolve_version_mapping(ref: str, expected: str) -> None:
    assert resolve_version(ref) == expected


@pytest.mark.parametrize("ref", [None, "", "refs/tags/not-a-version", "refs/tags/v1.2"])
def test_unknown_refs_resolve_to_dev(ref: str | None) -> None:
    assert resolve_version(ref) == "dev"


def test_too_long_workshop_tag_is_129_characters() -> None:
    assert len(TOO_LONG_WORKSHOP_TAG) == DOCKER_TAG_MAX_LENGTH + 1


@pytest.mark.parametrize(
    "ref",
    [
        "refs/tags/workshop-bad+id",
        f"refs/tags/{TOO_LONG_WORKSHOP_TAG}",
    ],
)
def test_invalid_workshop_tags_raise(ref: str) -> None:
    with pytest.raises(InvalidWorkshopTag):
        resolve_version(ref)


@pytest.mark.parametrize(
    "ref",
    [
        "refs/tags/workshop-bad+id",
        f"refs/tags/{TOO_LONG_WORKSHOP_TAG}",
    ],
)
def test_main_exits_non_zero_with_a_message_for_invalid_workshop_tags(
    ref: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITHUB_REF", ref)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    exit_code = main()

    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert ref.removeprefix("refs/tags/") in captured.err


def test_main_prints_the_resolved_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v0.2.0")
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)

    exit_code = main()

    assert exit_code == 0
    assert capsys.readouterr().out == "app_version=0.2.0\n"


def test_main_appends_to_github_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    github_output = tmp_path / "github_output"
    github_output.write_text("previous=value\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_REF", "refs/tags/workshop-2026-10")
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    exit_code = main()

    capsys.readouterr()
    assert exit_code == 0
    assert github_output.read_text(encoding="utf-8") == (
        "previous=value\napp_version=workshop-2026-10\n"
    )


def test_main_without_github_output_writes_no_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_OUTPUT", "")

    exit_code = main()

    assert exit_code == 0
    assert capsys.readouterr().out == "app_version=dev\n"


def _run_script(ref: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "GITHUB_OUTPUT"}
    env["GITHUB_REF"] = ref
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        check=False,
    )


def test_script_run_directly_succeeds_for_a_workshop_tag() -> None:
    result = _run_script("refs/tags/workshop-2026-10")

    assert result.returncode == 0
    assert result.stdout == "app_version=workshop-2026-10\n"


def test_script_run_directly_fails_for_an_invalid_workshop_tag() -> None:
    result = _run_script("refs/tags/workshop-bad+id")

    assert result.returncode != 0
    assert result.stdout == ""
    assert "workshop-bad+id" in result.stderr
