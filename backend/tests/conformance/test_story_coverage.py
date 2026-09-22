"""Offline story guard (design D4, tasks 3.3-3.5 and 5.3).

Runs in every ``uv run pytest backend/tests``: it needs no server and is not
marked ``conformance``. The first tests apply every guard rule to the
repository; the others apply single rules to ``tmp_path`` copies of the story
set and to temporary story modules, and show that each rule names the
offending criterion, flag, section or file.

Release mode (``CONFORMANCE_RELEASE=<tag>``) applies to the repository tests
as set in the environment; the ``tmp_path`` tests pass it explicitly (or set it
with ``monkeypatch``), so they behave the same in and out of release mode.
"""
from __future__ import annotations

import re
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from .stories import (
    GUARD_CHECKS,
    all_active_ids,
    check_decision_records,
    check_headings,
    check_index,
    check_markers,
    check_no_reuse,
    check_planted_bugs,
    check_record,
    check_release,
    load_index,
    load_stories,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_ROOT = REPO_ROOT / "docs" / "user-stories"
TESTS_ROOT = REPO_ROOT / "backend" / "tests"

#: Every active criterion ID, read from the story files at collection time.
ACTIVE_IDS = all_active_ids(DOCS_ROOT)

Row = tuple[str, str, str, str]


# ---------------------------------------------------------------------------
# The repository
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("check", GUARD_CHECKS, ids=lambda check: check.__name__)
def test_guard_rule_holds_for_the_repository(check) -> None:
    assert check(DOCS_ROOT, TESTS_ROOT) == []


@pytest.mark.parametrize("criterion", ACTIVE_IDS)
def test_criterion_is_referenceable(criterion: str) -> None:
    """Scenario "Downstream conversion": every criterion is ``<STORY>_<AC>``."""
    assert re.fullmatch(r"(WEB|API|AI)-\d{3}_AC-[1-9]\d*", criterion)


def test_active_ids_add_up_to_the_index_counts() -> None:
    index = load_index(DOCS_ROOT)

    assert len(ACTIVE_IDS) == sum(row.active_criteria or 0 for row in index.stories)
    assert len(ACTIVE_IDS) == len(set(ACTIVE_IDS))


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


#: The story set as imported (every row pending, no Revisions entry, no
#: withdrawal), frozen, so the rule tests below keep their premise while the
#: audit changes the live story set; the repository tests above use the live set.
BASELINE_ROOT = Path(__file__).resolve().parent / "fixtures" / "import-baseline"


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    """A private copy of the import-baseline story set."""
    root = tmp_path / "user-stories"
    shutil.copytree(BASELINE_ROOT, root)
    return root


@pytest.fixture
def tests_root(tmp_path: Path) -> Path:
    """An empty tests tree with a ``conformance/`` directory and no story module."""
    root = tmp_path / "tests"
    (root / "conformance").mkdir(parents=True)
    return root


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise LookupError(f"{old!r} not in {path.name}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def story_file(docs: Path, story: str) -> Path:
    (path,) = docs.glob(f"{story}_*.md")
    return path


def remove_heading(docs: Path, story: str, number: int) -> None:
    path = story_file(docs, story)
    text, count = re.subn(rf"^### AC-{number}: .*\n", "", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    if count != 1:
        raise LookupError(f"AC-{number} heading not found once in {path.name}")
    path.write_text(text, encoding="utf-8")


def add_heading(docs: Path, story: str, number: int, title: str) -> None:
    path = story_file(docs, story)
    edit(path, "\n## Test Data", f"\n### AC-{number}: {title}\n\nGiven a shopper\nThen it holds\n\n## Test Data")


def set_index_count(docs: Path, story: str, old: int, new: int) -> None:
    path = docs / "README.md"
    text, count = re.subn(
        rf"^(\| {story} \|.*\| ){old} \|$", rf"\g<1>{new} |", path.read_text(encoding="utf-8"), flags=re.MULTILINE
    )
    if count != 1:
        raise LookupError(f"index row of {story} with count {old} not found")
    path.write_text(text, encoding="utf-8")


def add_withdrawn(docs: Path, criterion: str, replacement: str) -> None:
    edit(
        docs / "README.md",
        "| ID | Version withdrawn | Reason | Replacement ID |\n|----|-------------------|--------|----------------|\n",
        "| ID | Version withdrawn | Reason | Replacement ID |\n|----|-------------------|--------|----------------|\n"
        f"| {criterion} | workshop-next | Clarified what the shopper sees | {replacement} |\n",
    )


def rows_for(docs: Path, status: str = "pending", overrides: Mapping[str, tuple[str, str, str]] | None = None) -> list[Row]:
    """One row per active criterion of ``docs``, with per-criterion overrides."""
    overrides = overrides or {}
    rows: list[Row] = []
    for cid in all_active_ids(docs):
        rows.append((cid, *overrides.get(cid, (status, "", ""))))
    return rows


def section_text(name: str, rows: Sequence[Row], no_criterion: Sequence[tuple[str, str]] = ()) -> str:
    lines = [f"## {name}", "", "- Image tag: TBD", "", "| Criterion | Status | Flag | Note |", "|---|---|---|---|"]
    lines += [f"| {cid} | {status} | {flag} | {note} |" for cid, status, flag, note in rows]
    lines += ["", "### Planted bugs without criterion", "", "| Flag | Reason |", "|------|--------|"]
    lines += [f"| {flag} | {reason} |" for flag, reason in no_criterion]
    return "\n".join(lines) + "\n"


def write_record(docs: Path, *sections: str) -> None:
    intro = "# Conformance record\n\nStatus semantics.\n\n## How deviations are resolved\n\nProse.\n\n"
    (docs / "CONFORMANCE.md").write_text(intro + "\n".join(sections), encoding="utf-8")


def module_path(tests_root: Path, story: str) -> Path:
    return tests_root / "conformance" / f"test_{story.lower().replace('-', '_')}_example.py"


def write_module(
    tests_root: Path,
    story: str,
    checks: Sequence[tuple[str, Sequence[str]]],
    *,
    pytestmark: bool = True,
) -> Path:
    """A story module with one check per ``(criterion, planted_bug flags)``."""
    lines = ["import pytest", ""]
    if pytestmark:
        lines += ["pytestmark = pytest.mark.conformance", ""]
    for number, (cid, flags) in enumerate(checks, start=1):
        lines += [f"@pytest.mark.planted_bug({flag!r})" for flag in flags]
        lines += [f"@pytest.mark.ac({cid!r})", f"def test_check_{number}(api):", "    pass", ""]
    path = module_path(tests_root, story)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def ids_of(docs: Path, story: str) -> list[str]:
    (found,) = [item for item in load_stories(docs) if item.id == story]
    return found.active_ids


def write_all_modules(docs: Path, tests_root: Path, flags: Mapping[str, Sequence[str]] | None = None) -> None:
    """A complete story module per story; ``flags`` adds planted_bug markers."""
    flags = flags or {}
    for story in load_stories(docs):
        write_module(tests_root, story.id, [(cid, flags.get(cid, ())) for cid in story.active_ids])


def offline_guard(docs: Path, tests_root: Path, release: str | None = None) -> dict[str, list[str]]:
    """Every guard rule with an explicit release mode."""
    results: dict[str, list[str]] = {}
    for check in GUARD_CHECKS:
        if check in (check_markers, check_planted_bugs, check_release):
            results[check.__name__] = check(docs, tests_root, release=release)
        else:
            results[check.__name__] = check(docs, tests_root)
    return results


def mentions(problems: Sequence[str], *needles: str) -> bool:
    return any(all(needle in problem for needle in needles) for problem in problems)


# ---------------------------------------------------------------------------
# Checks 1, 2, 6 and 8 (task 3.3)
# ---------------------------------------------------------------------------


def test_the_copy_passes_every_rule(docs: Path, tests_root: Path) -> None:
    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


def test_duplicate_heading_is_reported(docs: Path, tests_root: Path) -> None:
    edit(story_file(docs, "WEB-006"), "### AC-4: Email validation", "### AC-3: Email validation")

    problems = check_headings(docs, tests_root)

    assert mentions(problems, "WEB-006_complete_checkout.md", "duplicate heading WEB-006_AC-3")


def test_malformed_heading_is_reported(docs: Path, tests_root: Path) -> None:
    edit(story_file(docs, "WEB-006"), "### AC-4: Email validation", "### AC-4 Email validation")

    problems = check_headings(docs, tests_root)

    assert mentions(problems, "WEB-006_complete_checkout.md", "malformed criterion heading", "AC-4 Email validation")


def test_withdrawn_id_used_again_as_a_heading(docs: Path, tests_root: Path) -> None:
    add_withdrawn(docs, "WEB-006_AC-7", "WEB-006_AC-12")
    add_heading(docs, "WEB-006", 12, "Successful order submission (replacement)")

    problems = check_no_reuse(docs, tests_root)

    assert mentions(problems, "withdrawn criterion WEB-006_AC-7 is used again as a heading")


def test_story_file_missing_from_the_index(docs: Path, tests_root: Path) -> None:
    (docs / "WEB-008_new_story.md").write_text("# WEB-008: New\n\n### AC-1: Something\n\nGiven x\n", encoding="utf-8")

    problems = check_index(docs, tests_root)

    assert mentions(problems, "WEB-008_new_story.md", "missing from the index story table")


def test_index_count_must_match_the_headings(docs: Path, tests_root: Path) -> None:
    set_index_count(docs, "WEB-004", 8, 9)

    problems = check_index(docs, tests_root)

    assert mentions(problems, "WEB-004", "active criteria 9", "has 8")


def test_index_row_without_story_file(docs: Path, tests_root: Path) -> None:
    story_file(docs, "WEB-004").unlink()

    problems = check_index(docs, tests_root)

    assert mentions(problems, "WEB-004_search_products.md", "is not a story file")


def test_silently_removed_criterion_is_a_gap(docs: Path, tests_root: Path) -> None:
    remove_heading(docs, "WEB-006", 5)
    edit(docs / "CONFORMANCE.md", "| WEB-006_AC-5 | pending | | |\n", "")
    set_index_count(docs, "WEB-006", 11, 10)

    results = offline_guard(docs, tests_root)

    assert mentions(results["check_no_silent_removal"], "WEB-006_AC-5", "gap")
    assert results["check_headings"] == results["check_index"] == results["check_record"] == []


def released_and_unreleased(docs: Path) -> None:
    """``## Unreleased`` (pending) above ``## workshop-test`` (conforms)."""
    write_record(docs, section_text("Unreleased", rows_for(docs)), section_text("workshop-test", rows_for(docs, "conforms")))


def test_removed_released_criterion_is_reported(docs: Path, tests_root: Path) -> None:
    released_and_unreleased(docs)
    remove_heading(docs, "WEB-006", 11)
    edit(docs / "CONFORMANCE.md", "| WEB-006_AC-11 | pending |  |  |\n", "")
    set_index_count(docs, "WEB-006", 11, 10)

    results = offline_guard(docs, tests_root)

    assert mentions(results["check_no_silent_removal"], "WEB-006_AC-11", "'## workshop-test'", "removed silently")
    assert results["check_headings"] == results["check_index"] == results["check_record"] == []


def test_withdrawn_criterion_with_replacement_passes(docs: Path, tests_root: Path) -> None:
    """Scenario "Criterion withdrawn": the same removal, recorded, passes."""
    released_and_unreleased(docs)
    remove_heading(docs, "WEB-006", 11)
    add_heading(docs, "WEB-006", 12, "Validation errors display (replacement)")
    add_withdrawn(docs, "WEB-006_AC-11", "WEB-006_AC-12")
    edit(docs / "CONFORMANCE.md", "| WEB-006_AC-11 | pending |  |  |\n", "| WEB-006_AC-12 | pending |  |  |\n")

    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


# ---------------------------------------------------------------------------
# Check 3: marker coverage (task 3.4)
# ---------------------------------------------------------------------------


def test_no_story_modules_pass_until_release(docs: Path, tests_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario "Coverage check": the pending exemption ends in release mode."""
    monkeypatch.delenv("CONFORMANCE_RELEASE", raising=False)
    assert check_markers(docs, tests_root) == []

    monkeypatch.setenv("CONFORMANCE_RELEASE", "workshop-test")
    problems = check_markers(docs, tests_root)

    assert len(problems) == len(all_active_ids(docs))
    assert mentions(problems, "WEB-006_AC-7", "pytest.mark.ac('WEB-006_AC-7')")


def test_complete_story_module_passes(docs: Path, tests_root: Path) -> None:
    write_module(tests_root, "WEB-004", [(cid, ()) for cid in ids_of(docs, "WEB-004")])

    assert check_markers(docs, tests_root, release=None) == []


def test_story_module_ends_the_exemption_of_its_story(docs: Path, tests_root: Path) -> None:
    write_module(tests_root, "WEB-004", [(cid, ()) for cid in ids_of(docs, "WEB-004") if cid != "WEB-004_AC-8"])

    problems = check_markers(docs, tests_root, release=None)

    assert problems == ["WEB-004_AC-8: no check in its story module carries pytest.mark.ac('WEB-004_AC-8')"]


def test_typo_in_an_ac_marker(docs: Path, tests_root: Path) -> None:
    checks = [(cid, ()) for cid in ids_of(docs, "WEB-006")] + [("WEB-006_AC-77", ())]
    write_module(tests_root, "WEB-006", checks)

    problems = check_markers(docs, tests_root, release=None)

    assert mentions(problems, "unknown criterion WEB-006_AC-77")


def test_non_literal_ac_marker(docs: Path, tests_root: Path) -> None:
    path = write_module(tests_root, "WEB-004", [(cid, ()) for cid in ids_of(docs, "WEB-004")[1:]])
    path.write_text(
        path.read_text() + '\nID_VAR = "WEB-004_AC-1"\n\n\n@pytest.mark.ac(ID_VAR)\ndef test_variable(api):\n    pass\n'
    )

    problems = check_markers(docs, tests_root, release=None)

    assert mentions(problems, "test_variable", "string literal", "pytest.mark.ac(ID_VAR)")
    assert mentions(problems, "WEB-004_AC-1: no check")


def test_check_with_two_ac_markers(docs: Path, tests_root: Path) -> None:
    path = write_module(tests_root, "WEB-004", [(cid, ()) for cid in ids_of(docs, "WEB-004")])
    path.write_text(
        path.read_text()
        + '\n@pytest.mark.ac("WEB-004_AC-1")\n@pytest.mark.ac("WEB-004_AC-2")\ndef test_two(api):\n    pass\n'
    )

    problems = check_markers(docs, tests_root, release=None)

    assert mentions(problems, "test_two", "2 ac markers; exactly one required")


def test_check_without_ac_marker(docs: Path, tests_root: Path) -> None:
    path = write_module(tests_root, "WEB-004", [(cid, ()) for cid in ids_of(docs, "WEB-004")])
    path.write_text(path.read_text() + "\ndef test_unlabelled(api):\n    pass\n")

    problems = check_markers(docs, tests_root, release=None)

    assert mentions(problems, "test_unlabelled", "0 ac markers")


def test_ac_marker_outside_a_check_decorator(docs: Path, tests_root: Path) -> None:
    path = write_module(tests_root, "WEB-004", [(cid, ()) for cid in ids_of(docs, "WEB-004")])
    path.write_text(path.read_text().replace(
        "pytestmark = pytest.mark.conformance",
        'pytestmark = [pytest.mark.conformance, pytest.mark.ac("WEB-004_AC-1")]',
    ))

    problems = check_markers(docs, tests_root, release=None)

    assert mentions(problems, "test_web_004_example.py", "pytest.mark.ac outside a check function's decorators")


def test_story_module_without_pytestmark(docs: Path, tests_root: Path) -> None:
    write_module(tests_root, "WEB-004", [(cid, ()) for cid in ids_of(docs, "WEB-004")], pytestmark=False)

    problems = check_markers(docs, tests_root, release=None)

    assert problems == [
        "conformance/test_web_004_example.py: no module-level `pytestmark` containing `pytest.mark.conformance`"
    ]


@pytest.mark.parametrize("name", ["acceptance/checkout.robot", "conformance/keywords.resource"])
def test_robot_framework_file_is_reported(docs: Path, tests_root: Path, name: str) -> None:
    path = tests_root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("*** Test Cases ***\n")

    problems = check_markers(docs, tests_root, release=None)

    assert problems == [f"{name}: Robot Framework files are not allowed under the tests"]


# ---------------------------------------------------------------------------
# Checks 4, 5 and 7 (task 3.5)
# ---------------------------------------------------------------------------

NOTE = "Registered on purpose ([PR #1](https://github.com/manykarim/demo-webshop/pull/1))"
REASON = "No criterion covers it ([PR #2](https://github.com/manykarim/demo-webshop/pull/2))"


def test_duplicate_row(docs: Path, tests_root: Path) -> None:
    rows = rows_for(docs)
    write_record(docs, section_text("Unreleased", [*rows, ("WEB-006_AC-7", "pending", "", "")]))

    assert mentions(check_record(docs, tests_root), "duplicate row for WEB-006_AC-7")


def test_missing_row(docs: Path, tests_root: Path) -> None:
    rows = [row for row in rows_for(docs) if row[0] != "WEB-006_AC-7"]
    write_record(docs, section_text("Unreleased", rows))

    assert check_record(docs, tests_root) == ["'## Unreleased': missing row for active criterion WEB-006_AC-7"]


def test_row_for_a_withdrawn_criterion(docs: Path, tests_root: Path) -> None:
    remove_heading(docs, "WEB-006", 11)
    add_heading(docs, "WEB-006", 12, "Validation errors display (replacement)")
    add_withdrawn(docs, "WEB-006_AC-11", "WEB-006_AC-12")
    write_record(docs, section_text("Unreleased", [*rows_for(docs), ("WEB-006_AC-11", "pending", "", "")]))

    assert check_record(docs, tests_root) == ["'## Unreleased': row for withdrawn criterion WEB-006_AC-11"]


def test_row_for_an_unknown_criterion(docs: Path, tests_root: Path) -> None:
    write_record(docs, section_text("Unreleased", [*rows_for(docs), ("WEB-006_AC-40", "pending", "", "")]))

    assert check_record(docs, tests_root) == ["'## Unreleased': row for unknown criterion WEB-006_AC-40"]


@pytest.mark.parametrize(
    ("row", "problem"),
    [
        (("planted-bug", "", NOTE), "planted-bug without a flag"),
        (("conforms", "BUG_CHECKOUT_TOTAL", ""), "flag BUG_CHECKOUT_TOTAL on status 'conforms'"),
        (("story-corrected", "", ""), "story-corrected without a note"),
        (("app-fixed", "", ""), "app-fixed without a note"),
        (("planted-bug", "BUG_CHECKOUT_TOTAL", ""), "planted-bug without a note"),
        (("confirmed", "", ""), "unknown status 'confirmed'"),
    ],
    ids=["planted-bug-without-flag", "flag-on-conforms", "story-corrected-without-note",
         "app-fixed-without-note", "planted-bug-without-note", "unknown-status"],
)
def test_row_rules(docs: Path, tests_root: Path, row: tuple[str, str, str], problem: str) -> None:
    write_record(docs, section_text("Unreleased", rows_for(docs, overrides={"WEB-006_AC-1": row})))

    problems = check_record(docs, tests_root)

    assert len(problems) == 1
    assert mentions(problems, "WEB-006_AC-1", problem)


def test_pending_under_a_released_section(docs: Path, tests_root: Path) -> None:
    write_record(docs, section_text("workshop-test", rows_for(docs, overrides={"WEB-006_AC-3": ("pending", "", "")}, status="conforms")))

    problems = check_record(docs, tests_root)

    assert len(problems) == 1
    assert mentions(problems, "'## workshop-test' WEB-006_AC-3", "'pending' in the released section '## workshop-test'")


def test_unreleased_below_a_released_section(docs: Path, tests_root: Path) -> None:
    write_record(docs, section_text("workshop-test", rows_for(docs, "conforms")), section_text("Unreleased", rows_for(docs)))

    assert mentions(check_record(docs, tests_root), "'## Unreleased' is below the released section '## workshop-test'")


def test_two_unreleased_sections(docs: Path, tests_root: Path) -> None:
    write_record(docs, section_text("Unreleased", rows_for(docs)), section_text("Unreleased", rows_for(docs)))

    assert mentions(check_record(docs, tests_root), "2 '## Unreleased' sections")


def test_release_tag_must_name_the_top_section(docs: Path, tests_root: Path) -> None:
    write_record(docs, section_text("workshop-test", rows_for(docs, "conforms")))

    assert check_release(docs, tests_root, release="workshop-test") == []
    assert check_release(docs, tests_root, release="workshop-other") == [
        (
            "release mode CONFORMANCE_RELEASE=workshop-other: the top version section is '## workshop-test', "
            "expected '## workshop-other'"
        )
    ]


def test_release_mode_rejects_pending_rows(docs: Path, tests_root: Path) -> None:
    assert mentions(check_release(docs, tests_root, release="workshop-test"), "'## Unreleased'", "expected '## workshop-test'")
    assert mentions(check_release(docs, tests_root, release="workshop-test"), "95 pending rows")


def test_unknown_flag(docs: Path, tests_root: Path) -> None:
    write_record(docs, section_text("Unreleased", rows_for(docs, overrides={"WEB-006_AC-1": ("planted-bug", "BUG_NOPE", NOTE)})))
    write_module(tests_root, "WEB-006", [(cid, ("BUG_NOPE",) if cid == "WEB-006_AC-1" else ()) for cid in ids_of(docs, "WEB-006")])

    problems = check_planted_bugs(docs, tests_root, release=None)

    assert mentions(problems, "WEB-006_AC-1", "unknown planted-bug flag BUG_NOPE")
    assert mentions(problems, "test_check_1", "unknown planted-bug flag BUG_NOPE")


def test_marker_and_record_flag_must_match(docs: Path, tests_root: Path) -> None:
    write_record(docs, section_text("Unreleased", rows_for(docs, overrides={"WEB-004_AC-3": ("planted-bug", "BUG_WRONG_PRICE", NOTE)})))
    write_module(tests_root, "WEB-004", [(cid, ("BUG_MISSING_BUTTON",) if cid == "WEB-004_AC-3" else ()) for cid in ids_of(docs, "WEB-004")])

    problems = check_planted_bugs(docs, tests_root, release=None)

    assert problems == [
        (
            "WEB-004_AC-3: the record lists BUG_WRONG_PRICE, but no check of WEB-004_AC-3 carries "
            "pytest.mark.planted_bug('BUG_WRONG_PRICE')"
        ),
        (
            "WEB-004_AC-3: a check carries pytest.mark.planted_bug('BUG_MISSING_BUTTON'), but the record row "
            "does not list BUG_MISSING_BUTTON"
        ),
    ]


def multi_flag_fixture(docs: Path, tests_root: Path, markers: Sequence[str]) -> None:
    write_record(
        docs,
        section_text(
            "Unreleased",
            rows_for(docs, overrides={"WEB-002_AC-1": ("planted-bug", "BUG_MISSING_BUTTON, BUG_WRONG_PRICE", NOTE)}),
        ),
    )
    write_module(tests_root, "WEB-002", [(cid, tuple(markers) if cid == "WEB-002_AC-1" else ()) for cid in ids_of(docs, "WEB-002")])


def test_multi_flag_row_with_both_markers_passes(docs: Path, tests_root: Path) -> None:
    multi_flag_fixture(docs, tests_root, ["BUG_MISSING_BUTTON", "BUG_WRONG_PRICE"])

    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


def test_multi_flag_row_with_one_marker_names_the_missing_flag(docs: Path, tests_root: Path) -> None:
    multi_flag_fixture(docs, tests_root, ["BUG_MISSING_BUTTON"])

    assert check_planted_bugs(docs, tests_root, release=None) == [
        (
            "WEB-002_AC-1: the record lists BUG_WRONG_PRICE, but no check of WEB-002_AC-1 carries "
            "pytest.mark.planted_bug('BUG_WRONG_PRICE')"
        )
    ]


def test_conforms_row_may_note_an_incidental_break(docs: Path, tests_root: Path) -> None:
    note = "Also breaks while BUG_BROKEN_LINKS is on, incidentally ([PR #4](https://github.com/manykarim/demo-webshop/pull/4))"
    write_record(docs, section_text("Unreleased", rows_for(docs, overrides={"WEB-003_AC-5": ("conforms", "", note)})))
    # A decided row ends the pending exemption of its story, so WEB-003 needs its module.
    write_module(tests_root, "WEB-003", [(cid, ()) for cid in ids_of(docs, "WEB-003")])

    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


def test_pending_rows_with_empty_notes_pass(docs: Path, tests_root: Path) -> None:
    write_record(docs, section_text("Unreleased", rows_for(docs)))

    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


#: A complete record: every registered flag placed once.
COMPLETE_FLAGS = {
    "WEB-002_AC-1": ("BUG_MISSING_BUTTON", "BUG_WRONG_PRICE"),
    "WEB-003_AC-5": ("BUG_BROKEN_LINKS",),
    "WEB-006_AC-1": ("BUG_CHECKOUT_TOTAL",),
}


def complete_fixture(
    docs: Path,
    tests_root: Path,
    flags: Mapping[str, Sequence[str]] = COMPLETE_FLAGS,
    no_criterion: Sequence[tuple[str, str]] = (("BUG_SLOW_RESPONSE", REASON),),
    status: str = "conforms",
) -> None:
    overrides = {cid: ("planted-bug", ", ".join(values), NOTE) for cid, values in flags.items()}
    write_record(docs, section_text("Unreleased", rows_for(docs, status, overrides), no_criterion))
    write_all_modules(docs, tests_root, flags)


def test_complete_record_passes(docs: Path, tests_root: Path) -> None:
    complete_fixture(docs, tests_root)

    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


def test_registry_flag_in_neither_place(docs: Path, tests_root: Path) -> None:
    flags = {cid: values for cid, values in COMPLETE_FLAGS.items() if cid != "WEB-003_AC-5"}
    complete_fixture(docs, tests_root, flags)

    assert check_planted_bugs(docs, tests_root, release=None) == [
        (
            "BUG_BROKEN_LINKS: registered planted bug in no planted-bug row of '## Unreleased' and not under "
            "'Planted bugs without criterion'"
        )
    ]


def test_completeness_waits_for_the_last_pending_row(docs: Path, tests_root: Path) -> None:
    flags = {cid: values for cid, values in COMPLETE_FLAGS.items() if cid != "WEB-003_AC-5"}
    complete_fixture(docs, tests_root, flags, status="pending")

    assert check_planted_bugs(docs, tests_root, release=None) == []


def test_no_criterion_row_without_reason(docs: Path, tests_root: Path) -> None:
    complete_fixture(docs, tests_root, no_criterion=(("BUG_SLOW_RESPONSE", ""),))

    assert mentions(check_planted_bugs(docs, tests_root, release=None), "BUG_SLOW_RESPONSE", "no reason")


def test_no_criterion_reason_without_link(docs: Path, tests_root: Path) -> None:
    complete_fixture(docs, tests_root, no_criterion=(("BUG_SLOW_RESPONSE", "No criterion covers it"),))

    assert mentions(check_planted_bugs(docs, tests_root, release=None), "BUG_SLOW_RESPONSE", "no link")


def test_flag_in_a_row_and_in_the_no_criterion_table(docs: Path, tests_root: Path) -> None:
    complete_fixture(docs, tests_root, no_criterion=(("BUG_SLOW_RESPONSE", REASON), ("BUG_BROKEN_LINKS", REASON)))

    assert mentions(check_planted_bugs(docs, tests_root, release=None), "BUG_BROKEN_LINKS", "WEB-003_AC-5", "never both")


def test_unknown_flag_in_the_no_criterion_table(docs: Path, tests_root: Path) -> None:
    complete_fixture(docs, tests_root, no_criterion=(("BUG_SLOW_RESPONSE", REASON), ("BUG_NOPE", REASON)))

    assert mentions(check_planted_bugs(docs, tests_root, release=None), "unknown planted-bug flag 'BUG_NOPE'")


def test_heal_vs_hide_bug_only_without_criterion_in_release_mode(
    docs: Path, tests_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_record(docs, section_text("Unreleased", rows_for(docs), (("BUG_WRONG_PRICE", REASON),)))
    monkeypatch.setenv("CONFORMANCE_RELEASE", "workshop-test")

    problems = check_planted_bugs(docs, tests_root)

    assert mentions(problems, "BUG_WRONG_PRICE: enabled by preset drift_and_bug but recorded on no planted-bug row")
    assert mentions(problems, "BUG_WRONG_PRICE: enabled by preset drift_and_bug, so it must not be under")


# ---------------------------------------------------------------------------
# Check 9: decision records (task 5.3)
# ---------------------------------------------------------------------------

REVISION_REASON = "Clarified that the order total is subtotal plus shipping plus tax"


def add_revision(docs: Path, story: str, criterion: str, reason: str = REVISION_REASON) -> None:
    """Append a ``## Revisions`` entry for ``criterion`` to the story file."""
    path = story_file(docs, story)
    text = path.read_text(encoding="utf-8")
    if "\n## Revisions\n" not in text:
        text = text.rstrip("\n") + (
            "\n\n## Revisions\n\n| Version | Criterion | Original wording | New wording | Reason |\n"
            "|---------|-----------|------------------|-------------|--------|\n"
        )
    text += f"| workshop-next | {criterion} | Given a<br>Then b | Given a<br>Then c | {reason} |\n"
    path.write_text(text, encoding="utf-8")


def record_with(docs: Path, overrides: Mapping[str, tuple[str, str, str]]) -> None:
    write_record(docs, section_text("Unreleased", rows_for(docs, overrides=overrides)))


CORRECTED = ("story-corrected", "", NOTE)


def test_story_correction_with_revisions_entry_passes(docs: Path, tests_root: Path) -> None:
    record_with(docs, {"WEB-006_AC-1": CORRECTED})
    add_revision(docs, "WEB-006", "WEB-006_AC-1")
    write_module(tests_root, "WEB-006", [(cid, ()) for cid in ids_of(docs, "WEB-006")])

    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


def test_planted_bug_row_may_carry_a_revisions_entry(docs: Path, tests_root: Path) -> None:
    record_with(docs, {"WEB-006_AC-1": ("planted-bug", "BUG_CHECKOUT_TOTAL", NOTE)})
    add_revision(docs, "WEB-006", "WEB-006_AC-1")
    write_module(tests_root, "WEB-006", [(cid, ("BUG_CHECKOUT_TOTAL",) if cid == "WEB-006_AC-1" else ()) for cid in ids_of(docs, "WEB-006")])

    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


def test_withdrawal_with_replacement_and_revisions_entry_passes(docs: Path, tests_root: Path) -> None:
    """The README format: one entry for the replacement ID, whose reason names the withdrawn ID."""
    remove_heading(docs, "WEB-004", 4)
    add_heading(docs, "WEB-004", 9, "Search results replace the listing")
    add_withdrawn(docs, "WEB-004_AC-4", "WEB-004_AC-9")
    add_revision(docs, "WEB-004", "WEB-004_AC-9", "Replaces WEB-004_AC-4; results are shown after submitting the search")
    add_revision(docs, "WEB-004", "WEB-004_AC-4", "Clarified what the shopper sees")
    record_with(docs, {"WEB-004_AC-9": CORRECTED})
    write_module(tests_root, "WEB-004", [(cid, ()) for cid in ids_of(docs, "WEB-004")])

    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


def test_story_corrected_row_without_revisions_entry(docs: Path, tests_root: Path) -> None:
    record_with(docs, {"WEB-006_AC-7": CORRECTED})

    problems = check_decision_records(docs, tests_root)

    assert len(problems) == 1
    assert mentions(
        problems,
        "'## Unreleased' WEB-006_AC-7",
        "story-corrected, but WEB-006_complete_checkout.md has no '## Revisions' entry for WEB-006_AC-7",
    )


def test_revisions_entry_in_another_story_file_does_not_count(docs: Path, tests_root: Path) -> None:
    record_with(docs, {"WEB-006_AC-7": CORRECTED})
    add_revision(docs, "WEB-004", "WEB-006_AC-7")

    problems = check_decision_records(docs, tests_root)

    assert mentions(problems, "WEB-006_AC-7", "WEB-006_complete_checkout.md has no '## Revisions' entry")
    assert mentions(problems, "WEB-004_search_products.md", "WEB-006_AC-7, a criterion of another story")


def test_story_corrected_row_in_a_released_section_needs_an_entry(docs: Path, tests_root: Path) -> None:
    corrected = rows_for(docs, "conforms", {"WEB-003_AC-2": CORRECTED})
    write_record(docs, section_text("Unreleased", rows_for(docs)), section_text("workshop-test", corrected))

    problems = check_decision_records(docs, tests_root)

    assert mentions(problems, "'## workshop-test' WEB-003_AC-2", "WEB-003_view_product_detail.md has no '## Revisions' entry")


@pytest.mark.parametrize("status", ["conforms", "pending", "app-fixed"])
def test_revisions_entry_for_a_criterion_that_is_not_corrected(docs: Path, tests_root: Path, status: str) -> None:
    note = NOTE if status == "app-fixed" else ""
    record_with(docs, {"WEB-006_AC-7": (status, "", note)})
    add_revision(docs, "WEB-006", "WEB-006_AC-7")

    problems = check_decision_records(docs, tests_root)

    assert len(problems) == 1
    assert mentions(
        problems, "WEB-006_complete_checkout.md:", "'## Revisions' entry for WEB-006_AC-7", f"status {status!r}"
    )


def test_revisions_entry_for_a_criterion_without_row(docs: Path, tests_root: Path) -> None:
    add_revision(docs, "WEB-006", "WEB-006_AC-40")

    assert mentions(check_decision_records(docs, tests_root), "entry for WEB-006_AC-40", "no row in '## Unreleased'")


def test_revisions_entry_without_a_criterion_id(docs: Path, tests_root: Path) -> None:
    add_revision(docs, "WEB-006", "AC-7")

    assert mentions(check_decision_records(docs, tests_root), "WEB-006_complete_checkout.md", "'AC-7', which is not a criterion ID")


def test_missing_replacement_heading(docs: Path, tests_root: Path) -> None:
    remove_heading(docs, "WEB-006", 11)
    add_withdrawn(docs, "WEB-006_AC-11", "WEB-006_AC-12")
    edit(docs / "CONFORMANCE.md", "| WEB-006_AC-11 | pending | | |\n", "")
    set_index_count(docs, "WEB-006", 11, 10)

    results = offline_guard(docs, tests_root)

    assert len(results["check_decision_records"]) == 1
    assert mentions(
        results["check_decision_records"],
        "README.md:",
        "withdrawn WEB-006_AC-11: replacement WEB-006_AC-12 is not a '### AC-<n>' heading",
    )
    assert {name for name, problems in results.items() if problems} == {"check_decision_records"}


def test_withdrawal_without_replacement_needs_no_heading(docs: Path, tests_root: Path) -> None:
    remove_heading(docs, "WEB-006", 11)
    add_withdrawn(docs, "WEB-006_AC-11", "\u2014")
    edit(docs / "CONFORMANCE.md", "| WEB-006_AC-11 | pending | | |\n", "")
    set_index_count(docs, "WEB-006", 11, 10)

    assert offline_guard(docs, tests_root) == {check.__name__: [] for check in GUARD_CHECKS}


def test_replacement_withdrawn_later_is_answered_by_its_own_row(docs: Path, tests_root: Path) -> None:
    remove_heading(docs, "WEB-006", 11)
    add_heading(docs, "WEB-006", 13, "Validation errors display (second replacement)")
    add_withdrawn(docs, "WEB-006_AC-12", "WEB-006_AC-13")
    add_withdrawn(docs, "WEB-006_AC-11", "WEB-006_AC-12")
    edit(docs / "CONFORMANCE.md", "| WEB-006_AC-11 | pending | | |\n", "| WEB-006_AC-13 | pending | | |\n")

    assert check_decision_records(docs, tests_root) == []


def test_story_file_that_mentions_a_planted_bug(docs: Path, tests_root: Path) -> None:
    edit(story_file(docs, "WEB-002"), "## Notes\n", "## Notes\n\n- Prices are wrong while BUG_WRONG_PRICE is on.\n")

    problems = check_decision_records(docs, tests_root)

    assert len(problems) == 1
    assert mentions(problems, "WEB-002_browse_product_catalogue.md:", "mentions 'BUG_'")


def test_revisions_reason_that_mentions_a_drift_stage(docs: Path, tests_root: Path) -> None:
    record_with(docs, {"WEB-006_AC-1": CORRECTED})
    add_revision(docs, "WEB-006", "WEB-006_AC-1", "Keeps the total readable in drift stage 3")

    problems = check_decision_records(docs, tests_root)

    assert len(problems) == 1
    assert mentions(
        problems, "WEB-006_complete_checkout.md:", "(Revisions entry for WEB-006_AC-1)", "mentions 'drift'"
    )


@pytest.mark.parametrize(
    ("text", "token"),
    [
        ("The LOCATOR_STAGE setting changes nothing here.", "LOCATOR_"),
        ("A Planted defect is not part of this story.", "planted"),
        ("The layout may DRIFT between visits.", "drift"),
        ("See CONFORMANCE.md for the status.", "CONFORMANCE.md"),
        ("Checked by backend/tests/conformance.", "backend/tests"),
        ("Toggle bug_checkout_total to compare.", "BUG_"),
    ],
    ids=["locator", "planted-capitalised", "drift-upper-case", "record", "tests", "bug-lower-case"],
)
def test_forbidden_tokens_are_matched_ignoring_case(docs: Path, tests_root: Path, text: str, token: str) -> None:
    edit(story_file(docs, "API-007"), "## Notes\n", f"## Notes\n\n- {text}\n")

    problems = check_decision_records(docs, tests_root)

    assert len(problems) == 1
    assert mentions(problems, "API-007_user_login.md:", f"mentions {token!r}")
