"""`docs/WORKSHOP-FEATURES.md` is the contract, and it is checked (task 13.2).

The document is hand-written, so it can go stale in three ways, and all three
are failures here:

* a **stale row** - a hook the mapping no longer renames, or a replacement name
  that changed in `core/workshop.py` and not in the table;
* a **missing row** - a hook the mapping renames that no table mentions;
* an **undocumented rename** - a token that really disappears from, or appears
  in, a rendered page between stage 1 and stage N without a row that explains
  it. This is the spec scenario "Documentation check", and it is the reason the
  tokens are read from the *renders* and not from `STAGE_SPECS` alone.

The bug table is compared with `PLANTED_BUGS`, column by column and in registry
order.

**What is parsed.** Only the tables under `## Drift mapping` and under
`## Planted bugs` (design Decision 14), found by their headings - never by
position and never by counting the tables of the file. Every other section is
ignored, whether it holds prose (`## Workshop spaces`, owned by
`workshop-spaces`) or a table of its own, and two tolerance tests pin that
down.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.app.core.workshop import (
    COVERED_CLASSES,
    COVERED_IDS,
    DATA_TEST_VALUES,
    LAYOUT_COMPONENTS,
    PLANTED_BUGS,
    STAGE_SPECS,
    split_class_token,
)

from .conftest import COVERED_PAGES, Page
from .hooks import extract_hooks

#: The document under test. `parents[3]` is the repository root
#: (`backend/tests/contract/` -> `backend/tests/` -> `backend/` -> root).
DOC_PATH: Path = Path(__file__).resolve().parents[3] / "docs" / "WORKSHOP-FEATURES.md"

#: The headings whose tables are parsed, and nothing else.
MAPPING_HEADING = "## Drift mapping"
BUGS_HEADING = "## Planted bugs"

#: The fixed columns of a mapping table and of the bug table.
MAPPING_COLUMNS: tuple[str, ...] = ("Kind", "Stage 1", "Stage 2", "Stage 3", "Stage 4")
BUG_COLUMNS: tuple[str, ...] = ("Flag", "Flow", "Trigger", "Defect")

#: The drifted stages, in table-column order.
DRIFT_STAGES: tuple[int, ...] = (2, 3, 4)

#: "unchanged in this stage" - an em dash, as the document writes it.
DASH = "—"

#: What a `data-test` row shows for a stage that renders no such attribute.
REMOVED = "removed"

#: The kinds a mapping row may declare.
KINDS: tuple[str, ...] = ("id", "class-block", "class-exact", "data-test", "layout")

_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


# ---------------------------------------------------------------------------
# Parsing: tables under one heading
# ---------------------------------------------------------------------------


def _cells(line: str) -> tuple[str, ...]:
    """The cells of a Markdown table row, unwrapped from their code spans.

    A cell that is entirely a code span (`` `item-card` ``) is read as its
    content, so the tables stay readable while the comparison sees plain names.
    A cell with a code span *inside* prose keeps its backticks, which is what
    lets the bug table hold the registry's wording verbatim.
    """
    parts = [part.strip() for part in line.strip().strip("|").split("|")]
    unwrapped: list[str] = []
    for part in parts:
        if len(part) > 1 and part.startswith("`") and part.endswith("`") and "`" not in part[1:-1]:
            part = part[1:-1]
        unwrapped.append(part.strip())
    return tuple(unwrapped)


@dataclass(frozen=True)
class Table:
    """One parsed Markdown table: its header cells and its body rows."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def section_lines(text: str, heading: str) -> list[str]:
    """The lines under ``heading``, up to the next `##` heading."""
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:  # pragma: no cover - a renamed heading
        raise AssertionError(f"{DOC_PATH.name} has no {heading!r} section") from None
    out: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def tables_under(text: str, heading: str) -> tuple[Table, ...]:
    """Every Markdown table in the section ``heading`` introduces."""
    tables: list[Table] = []
    header: tuple[str, ...] | None = None
    rows: list[tuple[str, ...]] = []

    def flush() -> None:
        nonlocal header, rows
        if header is not None:
            tables.append(Table(header=header, rows=tuple(rows)))
        header, rows = None, []

    for line in section_lines(text, heading):
        stripped = line.strip()
        if not stripped.startswith("|"):
            flush()
            continue
        cells = _cells(stripped)
        if header is None:
            header = cells
            rows = []
            continue
        if all(_SEPARATOR_CELL.match(cell) for cell in cells):
            continue
        rows.append(cells)
    flush()
    return tuple(tables)


# ---------------------------------------------------------------------------
# The mapping rows, as the document states them and as the code means them
# ---------------------------------------------------------------------------

#: One mapping row: the kind, the stage-1 name, and the stage 2, 3 and 4 cells.
Row = tuple[str, str, str, str, str]


def documented_rows(text: str) -> tuple[Row, ...]:
    """Every row of every table under `## Drift mapping`, in document order."""
    rows: list[Row] = []
    for table in tables_under(text, MAPPING_HEADING):
        assert table.header == MAPPING_COLUMNS, (
            f"a mapping table has the columns {table.header}, expected {MAPPING_COLUMNS}"
        )
        for cells in table.rows:
            assert len(cells) == 5, f"a mapping row has {len(cells)} cells: {cells}"
            rows.append(tuple(cells))  # type: ignore[arg-type]
    return tuple(rows)


def _stage_cells(values: Mapping[int, str]) -> tuple[str, str, str]:
    return tuple(values.get(stage, DASH) for stage in DRIFT_STAGES)  # type: ignore[return-value]


def expected_rows() -> frozenset[Row]:
    """The mapping rows `core/workshop.py` implies, as a set.

    Ids, class blocks, exact class overrides, `data-test` values and the stage 4
    layout components - every table the shop drifts by, and nothing else.
    """
    rows: set[Row] = set()

    for key in COVERED_IDS:
        rows.add(("id", key, *_stage_cells({s: STAGE_SPECS[s].ids[key] for s in DRIFT_STAGES if key in STAGE_SPECS[s].ids})))

    for key in COVERED_CLASSES:
        rows.add(
            (
                "class-block",
                key,
                *_stage_cells(
                    {
                        s: STAGE_SPECS[s].classes.blocks[key]
                        for s in DRIFT_STAGES
                        if key in STAGE_SPECS[s].classes.blocks
                    }
                ),
            )
        )

    exact_keys = {key for spec in STAGE_SPECS.values() for key in spec.classes.exact}
    for key in exact_keys:
        rows.add(
            (
                "class-exact",
                key,
                *_stage_cells(
                    {
                        s: STAGE_SPECS[s].classes.exact[key]
                        for s in DRIFT_STAGES
                        if key in STAGE_SPECS[s].classes.exact
                    }
                ),
            )
        )

    for key in DATA_TEST_VALUES:
        rows.add(
            (
                "data-test",
                key,
                *_stage_cells(
                    {s: REMOVED for s in DRIFT_STAGES if not STAGE_SPECS[s].keep_data_test}
                ),
            )
        )

    for key in LAYOUT_COMPONENTS:
        rows.add(
            (
                "layout",
                key,
                *_stage_cells(
                    {s: STAGE_SPECS[s].layout[key] for s in DRIFT_STAGES if key in STAGE_SPECS[s].layout}
                ),
            )
        )

    return frozenset(rows)


def check_mapping_rows(text: str) -> list[str]:
    """Missing, stale or duplicated rows under `## Drift mapping`."""
    documented = documented_rows(text)
    problems: list[str] = []

    seen: set[tuple[str, str]] = set()
    for row in documented:
        kind, name = row[0], row[1]
        if kind not in KINDS:
            problems.append(f"the row {row} declares the unknown kind {kind!r}")
        if (kind, name) in seen:
            problems.append(f"{name!r} is documented twice as {kind!r}")
        seen.add((kind, name))

    expected = expected_rows()
    actual = frozenset(documented)
    for row in sorted(expected - actual):
        problems.append(f"the drift mapping is missing the row {row}")
    for row in sorted(actual - expected):
        problems.append(f"the drift mapping has a stale row the code does not imply: {row}")
    return problems


# ---------------------------------------------------------------------------
# Every rendered rename is explained by a row
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Explainer:
    """What the documented rows allow one stage to rename, and rename to."""

    id_from: frozenset[str]
    id_to: frozenset[str]
    exact_from: frozenset[str]
    exact_to: frozenset[str]
    block_from: frozenset[str]
    block_to: frozenset[str]

    def explains_removed_class(self, token: str) -> bool:
        """``token`` itself is renamed, or its block is.

        The whole token is looked up first, because a covered block name may
        itself contain a BEM separator: ``hero__search`` is a block of its own
        (the hero *search form* is the covered flow, not the hero), so deriving
        a block from it would look for ``hero`` and find nothing.
        """
        if token in self.exact_from or token in self.block_from:
            return True
        block, _ = split_class_token(token)
        return block in self.block_from

    def explains_added_class(self, token: str) -> bool:
        """``token`` is a declared replacement, or derived from one."""
        if token in self.exact_to or token in self.block_to:
            return True
        block, _ = split_class_token(token)
        return block in self.block_to


def explainer(rows: Sequence[Row], stage: int) -> Explainer:
    """The rows that apply to ``stage``, indexed for the token check."""
    column = DRIFT_STAGES.index(stage) + 2

    def pairs(kind: str) -> tuple[frozenset[str], frozenset[str]]:
        moved = {(row[1], row[column]) for row in rows if row[0] == kind and row[column] != DASH}
        return frozenset(name for name, _ in moved), frozenset(value for _, value in moved)

    id_from, id_to = pairs("id")
    exact_from, exact_to = pairs("class-exact")
    block_from, block_to = pairs("class-block")
    return Explainer(
        id_from=id_from,
        id_to=id_to,
        exact_from=exact_from,
        exact_to=exact_to,
        block_from=block_from,
        block_to=block_to,
    )


def check_rendered_tokens(
    rows: Sequence[Row], page_key: str, stage: int, baseline_html: str, stage_html: str
) -> list[str]:
    """Every token that moved between the two renders must have a row.

    Sets, not positions: an element never has to be aligned with its stage-1
    counterpart, which is what makes the check survive the stage 4 wrappers.
    """
    allowed = explainer(rows, stage)
    baseline = extract_hooks(baseline_html)
    current = extract_hooks(stage_html)
    problems: list[str] = []

    for value in sorted(baseline.ids - current.ids):
        if value not in allowed.id_from:
            problems.append(
                f"{page_key}: the id {value!r} is gone in stage {stage}, and no "
                f"documented row renames it there"
            )
    for value in sorted(current.ids - baseline.ids):
        if value not in allowed.id_to:
            problems.append(
                f"{page_key}: stage {stage} renders the id {value!r}, which no "
                f"documented row names as its replacement"
            )

    for token in sorted(baseline.classes - current.classes):
        if not allowed.explains_removed_class(token):
            problems.append(
                f"{page_key}: the class {token!r} is gone in stage {stage}, and no "
                f"documented row (or block rule) renames it there"
            )
    for token in sorted(current.classes - baseline.classes):
        if not allowed.explains_added_class(token):
            problems.append(
                f"{page_key}: stage {stage} renders the class {token!r}, which no "
                f"documented row (or block rule) names as a replacement"
            )

    return problems


# ---------------------------------------------------------------------------
# The bug table
# ---------------------------------------------------------------------------


def check_bug_table(text: str) -> list[str]:
    """The table under `## Planted bugs` equals `PLANTED_BUGS`, in order."""
    tables = tables_under(text, BUGS_HEADING)
    if len(tables) != 1:
        return [f"`{BUGS_HEADING}` holds {len(tables)} tables, expected exactly one"]

    table = tables[0]
    problems: list[str] = []
    if table.header != BUG_COLUMNS:
        problems.append(f"the bug table has the columns {table.header}, expected {BUG_COLUMNS}")

    expected = tuple((bug.flag, bug.flow, bug.trigger, bug.defect) for bug in PLANTED_BUGS)
    if table.rows != expected:
        for index, (documented, registered) in enumerate(
            zip(table.rows, expected, strict=False)
        ):
            if documented != registered:
                problems.append(f"bug row {index}: documented {documented}, registry {registered}")
        if len(table.rows) != len(expected):
            problems.append(
                f"the bug table has {len(table.rows)} rows, the registry has {len(expected)}"
            )
    return problems


# ---------------------------------------------------------------------------
# Fixtures and document variants
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def doc_text() -> str:
    """The document as it is committed."""
    return DOC_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def doc_rows(doc_text: str) -> tuple[Row, ...]:
    return documented_rows(doc_text)


def _replace_spaces_section(text: str, replacement: str) -> str:
    """Swap the `## Workshop spaces` section for ``replacement``."""
    head, marker, _ = text.partition("## Workshop spaces")
    assert marker, "the document has no `## Workshop spaces` section"
    return head + replacement


def _report(problems: Iterable[str]) -> str:
    return "\n".join(f"  - {problem}" for problem in problems)


# ---------------------------------------------------------------------------
# The checks themselves
# ---------------------------------------------------------------------------


def test_the_mapping_tables_equal_the_stage_specs(doc_text: str) -> None:
    """No missing, stale or duplicated row under `## Drift mapping`."""
    problems = check_mapping_rows(doc_text)

    assert not problems, f"{DOC_PATH}:\n{_report(problems)}"


def test_the_mapping_documents_every_layout_component(doc_rows: tuple[Row, ...]) -> None:
    """Stage 4 re-nests three components, and each has a `layout` row."""
    documented = {row[1] for row in doc_rows if row[0] == "layout"}

    assert documented == set(LAYOUT_COMPONENTS)


def test_the_bug_table_equals_the_registry(doc_text: str) -> None:
    """`## Planted bugs` is `PLANTED_BUGS`, column by column and in order."""
    problems = check_bug_table(doc_text)

    assert not problems, f"{DOC_PATH}:\n{_report(problems)}"


@pytest.mark.parametrize("stage", DRIFT_STAGES)
@pytest.mark.parametrize("page", COVERED_PAGES, ids=lambda page: page.key)
def test_every_rendered_rename_is_documented(
    rendered, fake_weasyprint, doc_rows: tuple[Row, ...], page: Page, stage: int
) -> None:
    """Spec scenario "Documentation check", on the whole page matrix."""
    problems = check_rendered_tokens(
        doc_rows, page.key, stage, rendered(page, 1), rendered(page, stage)
    )

    assert not problems, f"{DOC_PATH}:\n{_report(problems)}"


def test_the_document_sections_are_in_the_declared_order(doc_text: str) -> None:
    """The six sections this change owns, in order, then `## Workshop spaces`.

    Other changes may add sections of their own; they must not come between
    these, and `## Workshop spaces` stays last (design Decision 14).
    """
    headings = [line for line in doc_text.splitlines() if line.startswith("## ")]
    owned = [
        "## Stages and precedence",
        "## Stable contract",
        MAPPING_HEADING,
        BUGS_HEADING,
        "## Presets",
        "## Control endpoints",
    ]

    assert [heading for heading in headings if heading in owned] == owned
    assert headings[-1] == "## Workshop spaces", headings


# ---------------------------------------------------------------------------
# The check is a check: the negative case
# ---------------------------------------------------------------------------

#: The row the negative case removes. Any row would do; this one is rendered on
#: every full page, so the render-based check reports it as well.
DELETED_ROW = "| id | `primary-nav-menu` |"


def test_a_deleted_mapping_row_is_reported(doc_text: str, rendered, fake_weasyprint) -> None:
    """A copy of the document with one row removed fails both checks."""
    assert doc_text.count(DELETED_ROW) == 1, DELETED_ROW
    damaged = "\n".join(
        line for line in doc_text.splitlines() if not line.startswith(DELETED_ROW)
    )

    assert any("primary-nav-menu" in problem for problem in check_mapping_rows(damaged))

    rows = documented_rows(damaged)
    home = next(page for page in COVERED_PAGES if page.key == "home")
    token_problems = check_rendered_tokens(
        rows, home.key, 2, rendered(home, 1), rendered(home, 2)
    )
    assert any("primary-nav-menu" in problem for problem in token_problems), token_problems


# ---------------------------------------------------------------------------
# Tolerance: other sections do not affect the parse
# ---------------------------------------------------------------------------

_UNRELATED_SECTION = """## Release checklist

| Step | Owner |
|------|-------|
| Build the image | CI |
| Tag the candidate | CI |

"""

_PROSE_SPACES_SECTION = """## Workshop spaces

Every request runs inside a workshop space with its own flags and carts. This
section is prose and holds no table at all.
"""


def test_an_unrelated_section_with_its_own_table_is_ignored(doc_text: str) -> None:
    """A table somewhere else in the file is not a mapping or a bug table."""
    extended = _replace_spaces_section(doc_text, _UNRELATED_SECTION + _PROSE_SPACES_SECTION)

    assert not check_mapping_rows(extended)
    assert not check_bug_table(extended)
    assert documented_rows(extended) == documented_rows(doc_text)


def test_a_prose_spaces_section_after_the_control_endpoints_is_ignored(doc_text: str) -> None:
    """`workshop-spaces` owns that section; its content never reaches here."""
    replaced = _replace_spaces_section(doc_text, _PROSE_SPACES_SECTION)

    assert not check_mapping_rows(replaced)
    assert not check_bug_table(replaced)
