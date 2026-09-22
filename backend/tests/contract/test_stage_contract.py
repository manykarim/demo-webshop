"""The stage contract, page by page (drift-coverage tasks 4.3, 14.1, Decision 7).

The matrix is every page of ``COVERED_PAGES`` x stages 1 to 4 x the bug sets
``none`` and ``buggy``. For every cell this asserts, against the stage-1 render
of the *same build and the same bug set*:

1. the semantic snapshot is identical - the stage changed nothing a person or an
   assistive technology perceives, and a planted bug changes the same thing in
   every stage ("Bugs combine with drift");
2. the hooks changed exactly as the mapping declares (``hooks.py``);
3. the stage-1 selectors of the coverage oracle broke in exactly the stages that
   must break them (``coverage_oracle.py``);
4. stage 4 really re-nested every component it declares, found through stable
   hooks only (``structure_oracle.py``).

The rendered ``POST /checkout`` results are part of the matrix. The
confirmation is the one render whose content is not reproducible - every
submission creates a new order - so it is the one render compared through
``ORDER_RESULT_MASK``. Before masking, each confirmation is checked to carry
exactly one order number that resolves to a real order and two document links
that carry that order's id, so the placeholders cannot hide a missing number or
a broken link.

Every test of the matrix requests the root fixture ``fake_weasyprint``: the
confirmation cells place real orders, and whichever test renders such a cell
first must have the fake renderer installed.
"""
from __future__ import annotations

import re
import sqlite3

import pytest
from sqlalchemy.engine import make_url

from backend.app.core.workshop import BUG_FLAGS, STAGES

from .conftest import COVERED_PAGES, Page
from .coverage_oracle import (
    COVERAGE_ORACLE,
    SPEC_FLOWS,
    check_coverage,
    check_oracle_consistency,
)
from .hooks import check_stage_expectations
from .semantic import ORDER_RESULT_MASK, snapshot
from .structure_oracle import (
    anchors_for_page,
    check_declared_components,
    check_page_structure,
)

#: The bug sets of the matrix: the shop as it ships, and every registered bug.
BUG_SETS: dict[str, tuple[str, ...]] = {"none": (), "buggy": tuple(BUG_FLAGS)}

#: The order number a confirmation render shows.
_ORDER_NUMBER = re.compile(r"ORD-[0-9A-F]{8}")

#: The document links of a confirmation render, with the order id in them.
_DOCUMENT_HREF = re.compile(r"/api/docs/orders/(\d+)/(invoice|summary)\.pdf")

#: Selectors of the coverage oracle that name a ``data-test`` hook.
_DATA_TEST_SELECTOR = re.compile(r"\[\s*data-test\s*[=~|^$*]?=")


def _report(problems: list[str]) -> str:
    return "\n".join(f"  - {problem}" for problem in problems)


def _order_id_of(order_number: str) -> int:
    """The id of the order ``order_number``, read from the temporary database.

    The shop publishes no order-by-number endpoint, so the row is read straight
    from the database ``contract_client`` runs on - read-only, through the path
    ``settings`` holds while that client is active (the same reader
    ``test_checkout_totals.py`` uses).
    """
    from backend.app.core.config import settings

    database = make_url(settings.database_url).database
    assert database, f"no database file in {settings.database_url!r}"
    connection = sqlite3.connect(database)
    try:
        row = connection.execute(
            "SELECT id FROM orders WHERE order_number = ?", (order_number,)
        ).fetchone()
    finally:
        connection.close()

    assert row is not None, f"no order {order_number} in the database"
    return int(row[0])


def _check_order_result(html: str) -> None:
    """A confirmation render names one real order, in its text and both links."""
    numbers = set(_ORDER_NUMBER.findall(html))
    assert len(numbers) == 1, f"expected exactly one order number, found {sorted(numbers)}"
    order_number = numbers.pop()

    order_id = _order_id_of(order_number)

    documents = {kind: identifier for identifier, kind in _DOCUMENT_HREF.findall(html)}
    assert set(documents) == {"invoice", "summary"}, documents
    assert {int(value) for value in documents.values()} == {order_id}, (
        f"the document links of {order_number} point at {documents}, "
        f"but that order has id {order_id}"
    )


#: The parametrization of the bug dimension, as ``(id, flags)`` pairs.
_BUG_PARAMS = [pytest.param(flags, id=f"bugs-{name}") for name, flags in BUG_SETS.items()]


@pytest.mark.parametrize("bugs", _BUG_PARAMS)
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("page", COVERED_PAGES, ids=lambda page: page.key)
def test_semantic_snapshot_equals_stage_1(
    rendered, fake_weasyprint, page: Page, stage: int, bugs: tuple[str, ...]
) -> None:
    """Nothing a user perceives changes with the stage, bugs or not."""
    baseline_html = rendered(page, 1, bugs)
    stage_html = rendered(page, stage, bugs)

    replacements = None
    if page.masked:
        _check_order_result(baseline_html)
        _check_order_result(stage_html)
        replacements = ORDER_RESULT_MASK

    assert snapshot(stage_html, replacements) == snapshot(baseline_html, replacements)


@pytest.mark.parametrize("bugs", _BUG_PARAMS)
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("page", COVERED_PAGES, ids=lambda page: page.key)
def test_stage_moves_exactly_the_declared_hooks(
    rendered, fake_weasyprint, page: Page, stage: int, bugs: tuple[str, ...]
) -> None:
    """The ids, classes and test hooks moved exactly as the mapping says."""
    baseline = rendered(page, 1, bugs)
    current = rendered(page, stage, bugs)

    problems = check_stage_expectations(stage, baseline, current, anchors_for_page(page.key))

    assert not problems, f"{page.key} in stage {stage} with {bugs}:\n{_report(problems)}"


@pytest.mark.parametrize("bugs", _BUG_PARAMS)
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("page", COVERED_PAGES, ids=lambda page: page.key)
def test_coverage_oracle(
    rendered, fake_weasyprint, page: Page, stage: int, bugs: tuple[str, ...]
) -> None:
    """Stage-1 selectors break in exactly the stages the oracle names.

    A planted bug removes single elements - the hidden add-to-cart button of
    every fifth product - never a whole flow, so every entry still has something
    to match on the pages it is listed for.
    """
    problems = check_coverage(page.key, stage, rendered(page, stage, bugs))

    assert not problems, f"{page.key} in stage {stage} with {bugs}:\n{_report(problems)}"


@pytest.mark.parametrize("bugs", _BUG_PARAMS)
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("page", COVERED_PAGES, ids=lambda page: page.key)
def test_structural_oracle(
    rendered, fake_weasyprint, page: Page, stage: int, bugs: tuple[str, ...]
) -> None:
    """Every declared stage-4 layout is found through stable hooks and moved."""
    problems = check_page_structure(
        page.key, stage, rendered(page, 1, bugs), rendered(page, stage, bugs)
    )

    assert not problems, f"{page.key} in stage {stage} with {bugs}:\n{_report(problems)}"


def test_structural_oracle_covers_exactly_the_declared_layouts() -> None:
    """A layout that is declared but never checked, or the other way round."""
    problems = check_declared_components()

    assert not problems, _report(problems)


def test_coverage_oracle_is_internally_consistent() -> None:
    """Declared break stages match the hooks, and every flow is represented."""
    problems = check_oracle_consistency()

    assert not problems, _report(problems)


def test_every_spec_flow_is_covered_in_both_directions() -> None:
    """Flow completeness (task 14.1).

    Every flow of the spec's "Flow coverage" requirement has at least one
    ``data-test`` entry that breaks in stages 3 *and* 4 - the hooks a suite
    loses when the attributes go - and at least one id or class entry that
    breaks in stage 2 - the names a suite loses on the first rename. A flow with
    only one of the two would leave half of the drift unobserved.
    """
    problems: list[str] = []
    for flow in SPEC_FLOWS:
        entries = [entry for entry in COVERAGE_ORACLE if entry.flow == flow]
        if not any(
            _DATA_TEST_SELECTOR.search(entry.selector) and {3, 4} <= set(entry.breaks)
            for entry in entries
        ):
            problems.append(f"{flow!r} has no data-test entry that breaks in stages 3 and 4")
        if not any(
            not _DATA_TEST_SELECTOR.search(entry.selector) and 2 in entry.breaks
            for entry in entries
        ):
            problems.append(f"{flow!r} has no id or class entry that breaks in stage 2")

    assert not problems, _report(problems)


def test_every_covered_page_renders_something(rendered, fake_weasyprint) -> None:
    """No matrix cell is empty.

    The matrix asserts equality between cells; a page that answered with an
    empty body would make every comparison trivially true.
    """
    for page in COVERED_PAGES:
        html = rendered(page, 1)
        assert len(html) > 500, f"{page.key} rendered {len(html)} characters"
