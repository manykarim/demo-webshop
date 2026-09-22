"""Locator hooks of a rendered page, and what each stage must do to them.

Where ``semantic.py`` holds everything that must stay identical, this module
holds everything that must *move*: the ids, the class names and the
``data-test`` attributes a test author would locate elements by, plus the
ancestor tag chain that says where an element sits in the tree.

The per-stage expectations follow the spec's "Stage contract" requirement and
design Decision 3:

===== ================================================================
Stage Expectation against the stage-1 render of the same build
===== ================================================================
1     nothing moves
2     the ``data-test`` multiset is equal and not empty, covered ids and
      covered classes are renamed, ancestor chains are equal
3     no ``data-test`` at all, classes are equal, only covered
      *form-field* ids are renamed, ancestor chains are equal
4     no ``data-test`` at all, covered ids and covered classes are
      renamed, and the structural oracle holds (``structure_oracle.py``)
===== ================================================================

"Renamed" is checked against the mapping in ``backend/app/core/workshop``, not
merely as "different": every hook that disappears must be one the mapping covers,
every hook that appears must be a replacement that stage declares, and no covered
stage-1 hook may survive. A page that renders no covered hook of a kind at all -
a fragment without ids, say - must render none in the drifted stage either; the
coverage oracle is what keeps the matrix from passing vacuously.

Every check *returns* its problems as strings instead of asserting, so one test
can report all of them at once and so the checks themselves can be tested on
hand-written fixtures.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from backend.app.core.workshop import (
    COVERED_IDS,
    FORM_FIELD_IDS,
    STABLE_IDS,
    STAGE_SPECS,
    StageSpec,
    is_covered_class,
    split_class_token,
)

__all__ = [
    "Hooks",
    "ancestor_chain",
    "check_stage_expectations",
    "data_test_multiset",
    "extract_hooks",
    "matches",
    "selector_chains",
    "soup_of",
]

_PARSER = "html.parser"


def soup_of(html: str) -> BeautifulSoup:
    """Parse ``html`` with the one parser backend this suite uses."""
    return BeautifulSoup(html, _PARSER)


@dataclass(frozen=True)
class Hooks:
    """The locator hooks one render carries.

    ``ids`` and ``classes`` are sets: an id is unique by definition and a class
    name is a name, not an occurrence. ``data_test`` is a *multiset*, because
    stage 2 must keep every occurrence - a page that renders three
    ``add-to-cart-btn`` hooks in stage 1 and one in stage 2 has lost two, and a
    set would hide that.
    """

    ids: frozenset[str]
    classes: frozenset[str]
    data_test: Counter[str]

    @property
    def covered_ids(self) -> frozenset[str]:
        """The stage-1 ids of this render that the mapping covers."""
        return frozenset(value for value in self.ids if value in COVERED_IDS)

    @property
    def covered_classes(self) -> frozenset[str]:
        """The stage-1 class tokens of this render that the mapping covers."""
        return frozenset(value for value in self.classes if is_covered_class(value))

    @property
    def form_field_ids(self) -> frozenset[str]:
        """The stage-1 form-field ids of this render."""
        return frozenset(value for value in self.ids if value in FORM_FIELD_IDS)


def extract_hooks(html: str) -> Hooks:
    """The ids, class names and ``data-test`` values ``html`` renders.

    ``<template>`` content is included on purpose: the markup ``app.js`` clones
    from a template carries hooks into the live DOM, so it drifts with the rest
    (design Decision 6).
    """
    soup = soup_of(html)
    ids: set[str] = set()
    classes: set[str] = set()
    data_test: Counter[str] = Counter()

    for element in soup.find_all(True):
        element_id = element.get("id")
        if element_id:
            ids.add(str(element_id))
        for token in element.get("class") or ():
            if token:
                classes.add(str(token))
        hook = element.get("data-test")
        if hook is not None:
            data_test[str(hook)] += 1

    return Hooks(ids=frozenset(ids), classes=frozenset(classes), data_test=data_test)


def data_test_multiset(html: str) -> Counter[str]:
    """The ``data-test`` values of ``html``, with their occurrence counts."""
    return extract_hooks(html).data_test


def ancestor_chain(element: Tag) -> tuple[str, ...]:
    """The tag names from ``<body>`` (or the fragment root) down to ``element``.

    The element's own tag is not part of the chain: drift never changes it. The
    *depth* is what stage 4 changes, so the chain is compared as a whole and a
    single added wrapper is enough to make two chains differ.
    """
    chain: list[str] = []
    parent = element.parent
    while isinstance(parent, Tag) and parent.name != "[document]":
        chain.append(parent.name)
        if parent.name == "body":
            break
        parent = parent.parent
    return tuple(reversed(chain))


def matches(html: str, selector: str) -> list[Tag]:
    """Every element of ``html`` that matches the CSS ``selector``."""
    return list(soup_of(html).select(selector))


def selector_chains(html: str, selector: str) -> tuple[tuple[str, ...], ...]:
    """The ancestor chains of everything ``selector`` matches, in order."""
    return tuple(ancestor_chain(element) for element in matches(html, selector))


# ---------------------------------------------------------------------------
# What a stage is allowed to change
# ---------------------------------------------------------------------------


def _is_replacement_id(value: str, spec: StageSpec) -> bool:
    """Whether ``value`` is an id ``spec`` renames some covered id to."""
    return value in set(spec.ids.values())


def _is_replacement_class(value: str, spec: StageSpec) -> bool:
    """Whether ``value`` is a class name ``spec`` renames a covered class to.

    A block rename covers the names derived from it, so ``item-card__media`` is
    a stage-2 replacement because ``item-card`` is one.
    """
    if value in set(spec.classes.exact.values()):
        return True
    block, _ = split_class_token(value)
    return block in set(spec.classes.blocks.values())


def _rename_problems(
    kind: str,
    baseline: frozenset[str],
    current: frozenset[str],
    *,
    renamable: frozenset[str],
    is_replacement,
    must_differ: bool,
) -> list[str]:
    """Check that ``baseline`` became ``current`` by renaming only what it may.

    ``renamable`` is the set of stage-1 names this stage is allowed to move,
    ``is_replacement`` decides whether a newly appeared name is one this stage
    declares, and ``must_differ`` demands that at least one rename happened when
    the baseline had something to rename.
    """
    problems: list[str] = []
    removed = baseline - current
    added = current - baseline

    unexpected_removals = sorted(value for value in removed if value not in renamable)
    if unexpected_removals:
        problems.append(f"{kind} disappeared although the mapping does not rename them: {unexpected_removals}")

    unexpected_additions = sorted(value for value in added if not is_replacement(value))
    if unexpected_additions:
        problems.append(f"{kind} appeared that this stage does not declare as replacements: {unexpected_additions}")

    survivors = sorted(value for value in baseline & current if value in renamable)
    if survivors:
        problems.append(f"{kind} that this stage must rename are still rendered under their stage-1 name: {survivors}")

    renamable_baseline = sorted(baseline & renamable)
    if must_differ and renamable_baseline and not removed:
        problems.append(f"{kind} did not change although the render carries {renamable_baseline}")

    return problems


def _stable_id_problems(baseline: Hooks, current: Hooks) -> list[str]:
    """Ids that never drift must survive every stage untouched."""
    lost = sorted((baseline.ids & STABLE_IDS) - current.ids)
    return [f"stable ids are missing from the drifted render: {lost}"] if lost else []


def _data_test_problems(stage: int, baseline: Hooks, current: Hooks) -> list[str]:
    """Stages 1 and 2 keep every ``data-test``; stages 3 and 4 render none."""
    problems: list[str] = []
    if STAGE_SPECS[stage].keep_data_test:
        if current.data_test != baseline.data_test:
            problems.append(
                "the data-test multiset changed: "
                f"missing {sorted((baseline.data_test - current.data_test).elements())}, "
                f"extra {sorted((current.data_test - baseline.data_test).elements())}"
            )
        if not current.data_test:
            problems.append("the render carries no data-test attribute at all")
    elif current.data_test:
        problems.append(
            f"stage {stage} must render no data-test attribute, found "
            f"{sorted(current.data_test.elements())}"
        )
    return problems


def _chain_problems(
    baseline_html: str, current_html: str, anchors: Iterable[str], *, equal: bool
) -> list[str]:
    """Compare the ancestor chains of ``anchors`` between two renders."""
    problems: list[str] = []
    for selector in anchors:
        before = selector_chains(baseline_html, selector)
        after = selector_chains(current_html, selector)
        if not before:
            problems.append(f"the structural anchor {selector!r} matches nothing in the stage-1 render")
            continue
        if equal and before != after:
            problems.append(f"the nesting of {selector!r} changed: {before} became {after}")
        if not equal and before == after:
            problems.append(f"the nesting of {selector!r} did not change: still {before}")
    return problems


def check_stage_expectations(
    stage: int,
    baseline_html: str,
    stage_html: str,
    anchors: Sequence[str] = (),
) -> list[str]:
    """Every way ``stage_html`` breaks the stage contract against stage 1.

    ``anchors`` are the structural anchors of the page (CSS selectors built from
    stable hooks). Stages 2 and 3 must leave their nesting alone; stage 4 is
    checked by ``structure_oracle.check_structure`` instead, which also verifies
    that every declared layout component is covered.
    """
    if stage not in STAGE_SPECS:
        raise ValueError(f"unknown stage: {stage!r}")

    spec = STAGE_SPECS[stage]
    baseline = extract_hooks(baseline_html)
    current = extract_hooks(stage_html)

    problems = _data_test_problems(stage, baseline, current)
    problems += _stable_id_problems(baseline, current)

    renames_ids = bool(spec.ids)
    renamable_ids = frozenset(spec.ids)
    problems += _rename_problems(
        "ids",
        baseline.ids,
        current.ids,
        renamable=renamable_ids,
        is_replacement=lambda value: _is_replacement_id(value, spec),
        must_differ=renames_ids,
    )

    renamable_classes = frozenset(token for token in baseline.classes if is_covered_class(token))
    problems += _rename_problems(
        "classes",
        baseline.classes,
        current.classes,
        renamable=renamable_classes if spec.classes else frozenset(),
        is_replacement=lambda value: _is_replacement_class(value, spec),
        must_differ=bool(spec.classes),
    )

    if stage in (2, 3):
        problems += _chain_problems(baseline_html, stage_html, anchors, equal=True)

    return problems
