#!/usr/bin/env python3
"""Resolve the image version (``APP_VERSION``) from the git ref of a CI run.

The mapping is:

* ``refs/tags/workshop-<id>`` -> ``workshop-<id>``
* ``refs/tags/vX.Y.Z``        -> ``X.Y.Z``
* anything else               -> ``dev``

The resolved value is printed as ``app_version=<value>`` and, when
``GITHUB_OUTPUT`` is set, the same line is appended to that file so the value
becomes a step output.

A ``workshop-`` tag that would not be a valid Docker tag (characters outside
``[A-Za-z0-9_.-]``, or more than 128 characters in total) fails with a message
on stderr and a non-zero exit code, so the workflow stops before anything is
built or pushed.

Standard library only: this script runs before the project dependencies are
installed.
"""

from __future__ import annotations

import os
import re
import sys

DEFAULT_VERSION = "dev"
TAG_PREFIX = "refs/tags/"
WORKSHOP_PREFIX = "workshop-"

#: Docker tag character set, and the maximum tag length Docker accepts.
DOCKER_TAG_CHARS = re.compile(r"^[A-Za-z0-9_.-]+$")
DOCKER_TAG_MAX_LENGTH = 128

#: A version tag: ``vX.Y.Z`` with numeric components only.
SEMVER_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")

EXIT_OK = 0
EXIT_INVALID_REF = 1


class InvalidWorkshopTag(ValueError):
    """Raised when a ``workshop-`` tag is not a usable Docker tag."""


def resolve_version(ref: str | None) -> str:
    """Return the ``APP_VERSION`` for ``ref``.

    Raises :class:`InvalidWorkshopTag` for a ``workshop-`` tag that Docker
    would reject.
    """
    if not ref or not ref.startswith(TAG_PREFIX):
        return DEFAULT_VERSION

    tag = ref[len(TAG_PREFIX) :]

    if tag.startswith(WORKSHOP_PREFIX):
        _validate_workshop_tag(tag)
        return tag

    semver = SEMVER_TAG.match(tag)
    if semver:
        return semver.group(1)

    return DEFAULT_VERSION


def _validate_workshop_tag(tag: str) -> None:
    if len(tag) > DOCKER_TAG_MAX_LENGTH:
        raise InvalidWorkshopTag(
            f"workshop tag {tag!r} is {len(tag)} characters long, "
            f"but a Docker tag may be at most {DOCKER_TAG_MAX_LENGTH}"
        )
    if not DOCKER_TAG_CHARS.match(tag):
        invalid = sorted({character for character in tag if not DOCKER_TAG_CHARS.match(character)})
        raise InvalidWorkshopTag(
            f"workshop tag {tag!r} contains characters that are not allowed in a "
            f"Docker tag ([A-Za-z0-9_.-]): {''.join(invalid)}"
        )


def write_github_output(line: str) -> None:
    """Append ``line`` to ``$GITHUB_OUTPUT`` when that variable is set."""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if not github_output:
        return
    with open(github_output, "a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def main() -> int:
    ref = os.environ.get("GITHUB_REF")
    try:
        version = resolve_version(ref)
    except InvalidWorkshopTag as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_INVALID_REF

    line = f"app_version={version}"
    print(line)
    write_github_output(line)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
