"""Offline tests of the story, index and record parser (task 3.2).

Every test works on fixture strings or ``tmp_path`` files; nothing here needs a
server, a browser or the application.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .stories import (
    RecordLookupError,
    discover_story_files,
    lookup,
    parse_index,
    parse_record,
    parse_story,
)

STORY = """\
# WEB-042: Example Story

## Acceptance Criteria

### AC-1: First criterion
Given a shopper
When they look
Then they see

### AC-2 Missing colon
Given text

#### AC-3: Wrong heading level

### AC-04: Leading zero

### AC-5: Fifth criterion

```markdown
### AC-9: Inside a code block is not a heading
```

## Revisions

| Version | Criterion | Original wording | New wording | Reason |
|---------|-----------|------------------|-------------|--------|
| workshop-2026-10 | WEB-042_AC-5 | Given a<br>Then b | Given a<br>Then c | Clarified the wording |
"""

INDEX = """\
# User stories

## Stories

| ID | Title | File | Active criteria |
|----|-------|------|-----------------|
| WEB-042 | Example Story | [WEB-042_example.md](WEB-042_example.md) | 2 |
| API-001 | Other | [API-001_other.md](API-001_other.md) | 11 |

## Criterion IDs

- A story gets a revisions table:

  ```markdown
  | ID | Title | File | Active criteria |
  |----|-------|------|-----------------|
  | WEB-999 | Not a story | [x.md](x.md) | 1 |
  ```

## Withdrawn criteria

| ID | Version withdrawn | Reason | Replacement ID |
|----|-------------------|--------|----------------|
| WEB-042_AC-3 | workshop-2026-10 | Clarified what is checked | WEB-042_AC-6 |
"""

RECORD = """\
# Conformance record

Intro prose with a table that belongs to no version.

| Criterion | Status | Flag | Note |
|-----------|--------|------|------|
| WEB-000_AC-1 | pending | | |

## Unreleased

- Image tag: TBD
- Story commit: TBD

| Criterion | Status | Flag | Note |
|-----------|--------|------|------|
| WEB-006_AC-1 | planted-bug | BUG_MISSING_BUTTON, BUG_WRONG_PRICE | Both break the card ([PR #1](https://example.org/pr/1)) |
| WEB-006_AC-7 | pending | | |
| WEB-006_AC-7 | conforms | | |

### Planted bugs without criterion

| Flag | Reason |
|------|--------|
| BUG_SLOW_RESPONSE | No criterion bounds the response time ([PR #2](https://example.org/pr/2)) |

## How deviations are resolved

| Criterion | Status | Flag | Note |
|-----------|--------|------|------|
| WEB-006_AC-9 | conforms | | Prose example, not a version |

## workshop-2026-10

- Image tag: `workshop-2026-10`
- Image digest: `sha256:abc`

| Criterion | Status | Flag | Note |
|-----------|--------|------|------|
| WEB-006_AC-1 | conforms | | |
| WEB-006_AC-7 | planted-bug | BUG_CHECKOUT_TOTAL | Total omits tax ([PR #3](https://example.org/pr/3)) |

### Planted bugs without criterion

| Flag | Reason |
|------|--------|
"""


def test_story_headings_are_parsed_and_malformed_ones_rejected() -> None:
    story = parse_story(STORY, "WEB-042_example.md")

    assert story.id == "WEB-042"
    assert story.active_ids == ["WEB-042_AC-1", "WEB-042_AC-5"]
    assert [heading.title for heading in story.headings] == ["First criterion", "Fifth criterion"]
    assert [heading.text for heading in story.malformed] == [
        "### AC-2 Missing colon",
        "#### AC-3: Wrong heading level",
        "### AC-04: Leading zero",
    ]


def test_story_revisions_are_parsed() -> None:
    (revision,) = parse_story(STORY, "WEB-042_example.md").revisions

    assert revision.version == "workshop-2026-10"
    assert revision.criterion == "WEB-042_AC-5"
    assert revision.original == "Given a<br>Then b"
    assert revision.new == "Given a<br>Then c"
    assert revision.reason == "Clarified the wording"


def test_non_story_file_names_are_rejected() -> None:
    with pytest.raises(ValueError):
        parse_story(STORY, "notes.md")


def test_only_top_level_story_files_are_discovered(tmp_path: Path) -> None:
    (tmp_path / "WEB-042_example.md").write_text(STORY)
    (tmp_path / "API-001_other.md").write_text(STORY)
    (tmp_path / "README.md").write_text(INDEX)
    (tmp_path / "web-043_lowercase.md").write_text(STORY)
    (tmp_path / "WEB-044.md").write_text(STORY)
    (tmp_path / "legacy").mkdir()
    (tmp_path / "legacy" / "WEB-001_nested.md").write_text(STORY)

    assert [path.name for path in discover_story_files(tmp_path)] == [
        "API-001_other.md",
        "WEB-042_example.md",
    ]


def test_index_tables_are_read_per_section() -> None:
    index = parse_index(INDEX)

    assert index.problems == ()
    assert [(row.id, row.file, row.active_criteria) for row in index.stories] == [
        ("WEB-042", "WEB-042_example.md", 2),
        ("API-001", "API-001_other.md", 11),
    ]
    (withdrawn,) = index.withdrawn
    assert (withdrawn.id, withdrawn.version, withdrawn.replacement) == (
        "WEB-042_AC-3",
        "workshop-2026-10",
        "WEB-042_AC-6",
    )


def test_index_reports_missing_sections() -> None:
    index = parse_index("# User stories\n\n## Provenance\n\nNothing else.\n")

    assert index.problems == (
        "README.md: no '## Stories' section",
        "README.md: no '## Withdrawn criteria' section",
    )


def test_record_version_sections_skip_prose() -> None:
    record = parse_record(RECORD)

    assert [section.name for section in record.versions] == ["Unreleased", "workshop-2026-10"]
    assert record.prose == ("How deviations are resolved",)
    unreleased, released = record.versions
    assert not unreleased.released and released.released
    assert unreleased.header_lines == ("Image tag: TBD", "Story commit: TBD")
    assert released.header_lines == ("Image tag: `workshop-2026-10`", "Image digest: `sha256:abc`")
    assert "WEB-006_AC-9" not in {row.criterion for section in record.versions for row in section.rows}
    assert "WEB-000_AC-1" not in {row.criterion for section in record.versions for row in section.rows}


def test_record_multi_flag_cell_yields_two_keys() -> None:
    row = parse_record(RECORD).versions[0].rows[0]

    assert row.criterion == "WEB-006_AC-1"
    assert row.status == "planted-bug"
    assert row.flags == ("BUG_MISSING_BUTTON", "BUG_WRONG_PRICE")


def test_record_no_criterion_row_keeps_its_reason() -> None:
    unreleased, released = parse_record(RECORD).versions

    (entry,) = unreleased.no_criterion
    assert entry.flag == "BUG_SLOW_RESPONSE"
    assert entry.reason == "No criterion bounds the response time ([PR #2](https://example.org/pr/2))"
    assert released.no_criterion == ()


def test_lookup_returns_the_one_row_with_its_flags() -> None:
    record = parse_record(RECORD)

    row = lookup(record, "workshop-2026-10", "WEB-006_AC-7")

    assert row.status == "planted-bug"
    assert row.flags == ("BUG_CHECKOUT_TOTAL",)
    assert row.note == "Total omits tax ([PR #3](https://example.org/pr/3))"


def test_lookup_raises_on_a_duplicate_row() -> None:
    with pytest.raises(RecordLookupError, match="WEB-006_AC-7: 2 rows"):
        lookup(parse_record(RECORD), "Unreleased", "WEB-006_AC-7")


def test_lookup_raises_on_a_missing_row() -> None:
    with pytest.raises(RecordLookupError, match="WEB-006_AC-2: 0 rows"):
        lookup(parse_record(RECORD), "workshop-2026-10", "WEB-006_AC-2")


def test_lookup_raises_on_a_missing_version() -> None:
    with pytest.raises(RecordLookupError, match="workshop-2026-11"):
        lookup(parse_record(RECORD), "workshop-2026-11", "WEB-006_AC-7")
