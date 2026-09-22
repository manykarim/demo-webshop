"""The hand-written structural oracle (drift-coverage Decision 7, assertion 2).

Stage 4 re-nests three components. Which ones is declared in the mapping
(``STAGE_SPECS[4].layout``); *where* they are and how to find them without a
drifting hook is declared here, in the tests, so a layout that is announced but
never rendered - or rendered but never checked - fails.

Every anchor is a CSS selector built only from hooks the stable contract keeps:
content data attributes, form ``action`` and field ``name``. It must match at
least once on each page it is listed for, in every stage, so the check cannot
pass vacuously; and in stage 4 the ancestor tag chain of every match must differ
from the stage-1 chain of the same anchor.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from backend.app.core.workshop import STAGE_SPECS

from .hooks import selector_chains

__all__ = [
    "STRUCTURE_ORACLE",
    "StructureAnchor",
    "anchors_for_page",
    "check_declared_components",
    "check_page_structure",
]


@dataclass(frozen=True)
class StructureAnchor:
    """One way of finding a re-nested component without a drifting hook."""

    selector: str
    pages: tuple[str, ...]


#: The stage-4 layout components, each with the anchors that locate them.
#: The keys must equal ``STAGE_SPECS[4].layout`` - see
#: :func:`check_declared_components`.
STRUCTURE_ORACLE: Mapping[str, tuple[StructureAnchor, ...]] = {
    # Every card action on the listing. The listing shows no product hero, so
    # `button[data-product]` there is a card button and nothing else.
    "product-card": (StructureAnchor("button[data-product]", ("listing",)),),
    # The detail page's own product. Related and trending cards never show the
    # product the page is about, so this selector is the hero's button alone.
    "product-hero-actions": (StructureAnchor('button[data-product="3"]', ("detail",)),),
    # The checkout fields, found through the form's action and their own names,
    # on every render that shows the form: the two `GET /checkout` cells, the
    # empty-cart `POST /checkout` error render and the rejected submission with
    # its per-field messages. The confirmation render shows no form - the order
    # is placed - so it is not listed here.
    "checkout-field": tuple(
        StructureAnchor(
            f'form[action="/checkout"] [name="{field}"]',
            ("checkout-empty", "checkout-items", "checkout-post-empty", "checkout-post-invalid"),
        )
        for field in ("email", "name", "address", "team_size", "notes")
    ),
}


def anchors_for_page(
    page_key: str, oracle: Mapping[str, Sequence[StructureAnchor]] = STRUCTURE_ORACLE
) -> tuple[str, ...]:
    """Every anchor selector listed for ``page_key``, in declaration order."""
    return tuple(
        anchor.selector
        for anchors in oracle.values()
        for anchor in anchors
        if page_key in anchor.pages
    )


def check_declared_components(
    oracle: Mapping[str, Sequence[StructureAnchor]] = STRUCTURE_ORACLE,
) -> list[str]:
    """The oracle's components must be exactly the ones stage 4 declares."""
    declared = set(STAGE_SPECS[4].layout)
    checked = set(oracle)
    problems: list[str] = []
    if missing := sorted(declared - checked):
        problems.append(f"stage 4 declares layout components that no anchor checks: {missing}")
    if extra := sorted(checked - declared):
        problems.append(f"the structural oracle checks components stage 4 does not declare: {extra}")
    return problems


def check_page_structure(
    page_key: str,
    stage: int,
    baseline_html: str,
    stage_html: str,
    oracle: Mapping[str, Sequence[StructureAnchor]] = STRUCTURE_ORACLE,
) -> list[str]:
    """Structural problems of one page in one stage.

    Every anchor listed for the page must match in both renders; in stage 4 the
    nesting of each match must have changed.
    """
    problems: list[str] = []
    for component, anchors in oracle.items():
        for anchor in anchors:
            if page_key not in anchor.pages:
                continue
            before = selector_chains(baseline_html, anchor.selector)
            after = selector_chains(stage_html, anchor.selector)
            if not before:
                problems.append(
                    f"the {component} anchor {anchor.selector!r} matches nothing "
                    f"on {page_key} in stage 1"
                )
                continue
            if not after:
                problems.append(
                    f"the {component} anchor {anchor.selector!r} matches nothing "
                    f"on {page_key} in stage {stage}"
                )
                continue
            if stage == 4 and before == after:
                problems.append(
                    f"stage 4 declares a {component} layout, but the nesting of "
                    f"{anchor.selector!r} on {page_key} is unchanged: {before[0]}"
                )
    return problems
