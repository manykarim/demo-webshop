"""The one source of truth for locator drift, planted bugs and presets.

Everything the workshop changes about the rendered shop lives here (design
Decision 1): which hooks are covered, what each stage renames them to, which
defects are planted, and what the presets set. Templates, the stylesheet
variants, the control endpoints, the seeded flag rows and the contract tests all
derive from these tables, so a hook cannot drift in one place and stay put in
another.

Reading order:

* **Stages** - :data:`LOCATOR_FLAGS` and :func:`effective_stage` (design
  Decision 2): the highest enabled locator flag wins, stage 1 is the absence of
  all of them.
* **Covered hooks** - :data:`COVERED_IDS`, :data:`COVERED_CLASSES`,
  :data:`DATA_TEST_VALUES` and the ids that never drift, :data:`STABLE_IDS`.
* **The mapping** - one :class:`StageSpec` per stage in :data:`STAGE_SPECS`.
* **The template helpers** - :class:`DriftView` (``drift``) and
  :class:`BugView` (``bugs``), bundled per request in :class:`WorkshopView` and
  reached from Jinja through the proxies :data:`drift_global` and
  :data:`bugs_global`.
* **The bug registry** - :data:`PLANTED_BUGS` (design Decision 9), which drives
  the bug view, the seeded flag rows, the status endpoint and the docs table.
* **The presets** - :func:`build_presets` (design Decision 12).

Flags reach this module only as a plain ``dict[str, bool]`` from the seam
``core/feature_flags.get_effective_flags``; nothing here queries the database.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from fastapi import Depends, Request
from markupsafe import Markup
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from .feature_flags import get_effective_flags

# ---------------------------------------------------------------------------
# Stages and precedence (design Decision 2)
# ---------------------------------------------------------------------------

#: The locator stages the shop renders. Stage 1 is the absence of locator flags
#: (there is no ``LOCATOR_V1``), so it has no flag of its own.
STAGES: Final[tuple[int, ...]] = (1, 2, 3, 4)

#: The locator flags, in stage order: index + 2 is the stage a flag selects.
LOCATOR_FLAGS: Final[tuple[str, ...]] = ("LOCATOR_V2", "LOCATOR_V3", "LOCATOR_V4")

#: The flag that selects a stage, for the stages that have one.
LOCATOR_FLAG_BY_STAGE: Final[Mapping[int, str]] = MappingProxyType(
    {index + 2: flag for index, flag in enumerate(LOCATOR_FLAGS)}
)


def effective_stage(flags: Mapping[str, bool]) -> int:
    """The stage ``flags`` selects: the highest enabled locator flag wins.

    4 if ``LOCATOR_V4``, else 3 if ``LOCATOR_V3``, else 2 if ``LOCATOR_V2``,
    else 1. This is the only implementation of the precedence; the status
    endpoint reports ``f"v{effective_stage(flags)}"`` and :class:`DriftView`
    renders the stage it returns.
    """
    for stage in reversed(STAGES[1:]):
        if flags.get(LOCATOR_FLAG_BY_STAGE[stage]):
            return stage
    return 1


# ---------------------------------------------------------------------------
# Covered hooks (design Decision 1 and Decision 3)
# ---------------------------------------------------------------------------

#: Element ids that never drift, in any stage, and are therefore the only ids a
#: template may write literally (the template scan of task 5.10 allows exactly
#: these): the skip-link target, the price filter's two range inputs and the
#: three newsletter ids, because neither the filter panel nor the newsletter is
#: a covered flow (design Decision 3 and the Non-Goals).
STABLE_IDS: Final[frozenset[str]] = frozenset(
    {
        "main-content",
        "price-min-range",
        "price-max-range",
        "newsletter-email",
        "newsletter-hint",
        "newsletter-alert",
    }
)

#: The subset of :data:`COVERED_IDS` that belongs to form fields. Stage 3
#: renames exactly these (design Decision 1: stage 3 "has entries only for
#: form-field ids"), because a stage that only removes ``data-test`` would leave
#: every form untouched.
FORM_FIELD_IDS: Final[frozenset[str]] = frozenset(
    {
        # Sign-in modal (task 5.6)
        "auth-email",
        "auth-password",
        # Chat widget (task 5.7)
        "chat-input",
        # Checkout form (task 5.9)
        "checkout-email",
        "checkout-name",
        "checkout-address",
        "checkout-team-size",
        "checkout-notes",
    }
)

#: Covered element ids, by their stage-1 name. Every one of them is rendered
#: through ``drift.id(...)`` and renamed in stages 2 and 4; the form-field ids
#: above are renamed in stage 3 as well.
#:
#: Two of them are also covered *class* names: ``search-results`` (task 5.3) and
#: ``checkout-alert`` (task 5.9). Ids and classes are separate tables with
#: separate replacements, so the two ``## Drift mapping`` rows stay
#: distinguishable by their ``Kind`` and no replacement name is reused.
#:
#: The product card has no id; the listing, cart and detail pages render as many
#: cards as they like, so a card hook can only be a class or a ``data-test``.
COVERED_IDS: Final[frozenset[str]] = FORM_FIELD_IDS | frozenset(
    {
        # Navigation (task 5.5)
        "primary-nav-menu",
        # Sign-in modal and account menu (task 5.6)
        "auth-modal",
        "auth-modal-title",
        "account-panel",
        # Chat widget and add-to-cart confirmation (task 5.7)
        "chat-widget",
        "flash-message",
        # Search results container, on both search pages (task 5.3)
        "search-results",
        # The typeahead listbox inside the suggestion dropdown template, on
        # both search pages (task 9.3): the id is rendered into the
        # `<template>` the script clones, so the markup it builds drifts too.
        "search-suggestions",
        # Checkout form (task 5.9)
        "checkout-email-hint",
        "checkout-alert",
        # The per-field messages of a rejected checkout submission, which the
        # field's aria-describedby points at (acceptance-conformance,
        # WEB-006_AC-4 to AC-6 and AC-11)
        "checkout-email-error",
        "checkout-name-error",
        "checkout-address-error",
    }
)

#: Covered CSS class names, by their stage-1 name. Each entry is treated as a
#: BEM *block*: its ``block__element`` and ``block--modifier`` names are covered
#: too and follow the block rename without a table row of their own
#: (:func:`covering_class`).
#:
#: Uncovered on purpose (design Decision 3): the shared blocks ``button`` with
#: its modifiers and ``form-field``, the state classes (``is-*``, ``theme-dark``,
#: ``site-nav-open``, ``has-chat-open``), ``category-badge``, ``theme-toggle``
#: and the space indicator of ``workshop-spaces``. So are the blocks of the
#: uncovered flows: ``newsletter*``, the filter panel, ``chip*``, ``section*``,
#: ``empty-state``, ``cart-items``, ``cart-layout`` and ``checkout-auth-note``.
#:
#: ``hero__search`` is registered as an entry of its own rather than through the
#: block ``hero``: the covered flow is the hero *search form* (design Decision 3
#: and task 5.3), which ``products.html`` renders too, while the rest of the
#: home hero is not a workshop flow.
COVERED_CLASSES: Final[frozenset[str]] = frozenset(
    {
        # Navigation and cart badge (task 5.5)
        "site-nav",
        "badge",
        # Sign-in modal and account menu (task 5.6)
        "auth-modal",
        "account-dropdown",
        # Chat widget and add-to-cart confirmation (task 5.7)
        "chat-widget",
        "chat-launcher",
        "chat-message",
        "flash",
        # Search and product grids, on both search pages (task 5.3)
        "hero__search",
        "search-results",
        "product-grid",
        # Listing and cards (task 5.2)
        "product-card",
        # Product detail (task 5.4)
        "product-hero",
        # Cart (task 5.8)
        "cart-item",
        "cart-summary",
        # Checkout form, summary and result (task 5.9)
        "checkout-form",
        "checkout-summary",
        "checkout-alert",
    }
)

#: The ``data-test`` values the shop renders, by their stage-1 value. Stages 1
#: and 2 render them through ``drift.test(...)``, stages 3 and 4 render nothing.
#: Every covered flow has at least one (design Decision 3, A4), and values are
#: unique per element kind where one page shows both, which is why the detail
#: page's add-to-cart button is ``detail-add-to-cart`` and not
#: ``add-to-cart-btn``: the related cards below it carry that one.
DATA_TEST_VALUES: Final[frozenset[str]] = frozenset(
    {
        # Product cards (task 5.2)
        "product-card",
        "product-link",
        "product-price",
        "add-to-cart-btn",
        "view-details-link",
        # The listing's product count (acceptance-conformance, WEB-002_AC-6)
        "product-count",
        # Search, on both search pages (task 5.3)
        "search-input",
        "search-submit",
        "search-clear",
        # Product detail (task 5.4)
        "detail-add-to-cart",
        # The detail route's not-found render (acceptance-conformance, WEB-003_AC-9)
        "product-not-found",
        # Navigation and cart badge (task 5.5)
        "cart-count",
        # Sign-in modal and account menu (task 5.6)
        "login-button",
        "auth-email-input",
        "auth-password-input",
        "auth-submit",
        "auth-close",
        "account-menu-trigger",
        "account-logout",
        # Chat widget (task 5.7)
        "chat-launcher",
        "chat-input",
        # Cart (task 5.8)
        "cart-item",
        "cart-total",
        # Checkout (task 5.9)
        "checkout-email-input",
        "checkout-name-input",
        "checkout-address-input",
        "checkout-team-size-input",
        "checkout-notes-input",
        "checkout-submit",
        "checkout-result",
        # Checkout summary (task 10.2): the amounts the summary shows, so a
        # suite that reads totals by `data-test` loses them in stages 3 and 4.
        "checkout-subtotal",
        "checkout-tax",
        "checkout-total",
        # The per-field messages of a rejected checkout submission
        # (acceptance-conformance, WEB-006_AC-4 to AC-6 and AC-11)
        "checkout-email-error",
        "checkout-name-error",
        "checkout-address-error",
    }
)

#: The components that have a structural variant in stage 4, exhaustively
#: (design Decision 3). ``drift.layout(...)`` accepts only these names.
LAYOUT_COMPONENTS: Final[tuple[str, ...]] = (
    "product-card",
    "product-hero-actions",
    "checkout-field",
)

#: The BEM separators. A class token's block is the text before whichever of
#: them occurs first.
_BEM_SEPARATORS: Final[tuple[str, ...]] = ("__", "--")


def split_class_token(token: str) -> tuple[str, str]:
    """Split a class token into its block and the rest.

    ``"product-card__title"`` becomes ``("product-card", "__title")`` and
    ``"product-card"`` becomes ``("product-card", "")``. The block is the text
    before the *first* BEM separator, so ``"site-nav__link--cart"`` belongs to
    the block ``site-nav``.
    """
    positions = [index for index in (token.find(sep) for sep in _BEM_SEPARATORS) if index > 0]
    if not positions:
        return token, ""
    cut = min(positions)
    return token[:cut], token[cut:]


def covering_class(token: str) -> str | None:
    """The covered class name ``token`` belongs to, or ``None``.

    A token is covered when it is itself in :data:`COVERED_CLASSES` or when it
    is a ``block__element`` / ``block--modifier`` name of a covered block. This
    is the one derivation rule; the template scan (task 5.10) and the stylesheet
    rewrite (group 6) use it instead of repeating the ``__``/``--`` handling.
    """
    if token in COVERED_CLASSES:
        return token
    block, suffix = split_class_token(token)
    if suffix and block in COVERED_CLASSES:
        return block
    return None


def is_covered_class(token: str) -> bool:
    """Whether ``token`` is a covered class name (including derived names)."""
    return covering_class(token) is not None


# ---------------------------------------------------------------------------
# The mapping (design Decision 1)
# ---------------------------------------------------------------------------


class UnknownHook(KeyError):
    """A template asked for a hook that is not in the mapping.

    Keys are strict on purpose: a typo in a template must fail the contract
    tests instead of silently rendering a name that never drifts.
    """


def _frozen(mapping: Mapping[str, str] | None) -> Mapping[str, str]:
    """A read-only copy of ``mapping``, so a table cannot be edited at runtime."""
    return MappingProxyType(dict(mapping or {}))


@dataclass(frozen=True)
class ClassMap:
    """The class renames of one stage.

    ``blocks`` renames a covered block and every ``block__*`` and ``block--*``
    name derived from it. ``exact`` overrides one specific name and wins over
    the block rule, which is how ``product-card__add`` becomes ``btn-main`` in
    stage 2 while its siblings follow the block into ``item-card__*``.
    """

    blocks: Mapping[str, str] = field(default_factory=dict)
    exact: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", _frozen(self.blocks))
        object.__setattr__(self, "exact", _frozen(self.exact))

    def __bool__(self) -> bool:
        return bool(self.blocks or self.exact)

    @property
    def replacements(self) -> tuple[str, ...]:
        """Every replacement name this stage renames a class to."""
        return tuple(self.blocks.values()) + tuple(self.exact.values())


@dataclass(frozen=True)
class StageSpec:
    """Everything one stage changes.

    ``ids`` maps a stage-1 id to its replacement, ``classes`` holds the block
    renames and the exact overrides, ``keep_data_test`` is true only for stage 2
    (stage 1 keeps them too, but it renames nothing at all), and ``layout``
    names the structural variant of a component - stage 4 only.
    """

    stage: int
    ids: Mapping[str, str] = field(default_factory=dict)
    classes: ClassMap = field(default_factory=ClassMap)
    keep_data_test: bool = False
    layout: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ids", _frozen(self.ids))
        object.__setattr__(self, "layout", _frozen(self.layout))


#: The mapping, one entry per stage. Stage 1 renames nothing and keeps
#: ``data-test``; it is listed so every stage is built the same way.
#:
#: The card block names ``item-card`` (stage 2) and ``product-tile`` (stage 4)
#: are fixed: ``rendered_stage()`` in ``backend/tests/spaces/helpers.py``
#: recognises the stage by them.
STAGE_SPECS: Final[Mapping[int, StageSpec]] = MappingProxyType(
    {
        1: StageSpec(stage=1, keep_data_test=True),
        2: StageSpec(
            stage=2,
            ids={
                "primary-nav-menu": "main-nav-list",
                "auth-modal": "signin-overlay",
                "auth-modal-title": "signin-heading",
                "auth-email": "login-email",
                "auth-password": "login-password",
                "account-panel": "user-menu-panel",
                "chat-widget": "assistant-panel",
                "chat-input": "assistant-question",
                "flash-message": "toast-message",
                "search-results": "results-list",
                "search-suggestions": "suggest-list",
                "checkout-email": "order-email",
                "checkout-name": "order-name",
                "checkout-address": "order-address",
                "checkout-team-size": "order-team-size",
                "checkout-notes": "order-notes",
                "checkout-email-hint": "order-email-hint",
                "checkout-alert": "order-alert",
                "checkout-email-error": "order-email-error",
                "checkout-name-error": "order-name-error",
                "checkout-address-error": "order-address-error",
            },
            classes=ClassMap(
                blocks={
                    "site-nav": "main-nav",
                    "badge": "count-bubble",
                    "auth-modal": "signin-modal",
                    "account-dropdown": "user-menu",
                    "chat-widget": "assistant-widget",
                    "chat-launcher": "assistant-launcher",
                    "chat-message": "assistant-message",
                    "flash": "toast",
                    "hero__search": "banner-search",
                    "search-results": "results-panel",
                    "product-grid": "item-collection",
                    "product-card": "item-card",
                    "product-hero": "detail-hero",
                    "cart-item": "basket-line",
                    "cart-summary": "basket-totals",
                    "checkout-form": "order-form",
                    "checkout-summary": "order-totals",
                    "checkout-alert": "order-notice",
                },
                exact={
                    "product-card__title": "item-title",
                    "product-card__price": "item-cost",
                    "product-card__cta": "item-actions",
                    "product-card__add": "btn-main",
                },
            ),
            keep_data_test=True,
        ),
        3: StageSpec(
            stage=3,
            ids={
                "auth-email": "signin-email",
                "auth-password": "signin-password",
                "chat-input": "chat-question",
                "checkout-email": "buyer-email",
                "checkout-name": "buyer-name",
                "checkout-address": "buyer-address",
                "checkout-team-size": "buyer-team-size",
                "checkout-notes": "buyer-notes",
            },
        ),
        4: StageSpec(
            stage=4,
            ids={
                "primary-nav-menu": "nav-drawer",
                "auth-modal": "login-layer",
                "auth-modal-title": "login-layer-title",
                "auth-email": "account-email",
                "auth-password": "account-password",
                "account-panel": "profile-flyout",
                "chat-widget": "concierge-dock",
                "chat-input": "concierge-question",
                "flash-message": "notice-banner",
                "search-results": "finder-results",
                "search-suggestions": "typeahead-options",
                "checkout-email": "payment-email",
                "checkout-name": "payment-name",
                "checkout-address": "payment-address",
                "checkout-team-size": "payment-team-size",
                "checkout-notes": "payment-notes",
                "checkout-email-hint": "payment-email-hint",
                "checkout-alert": "payment-alert",
                "checkout-email-error": "payment-email-error",
                "checkout-name-error": "payment-name-error",
                "checkout-address-error": "payment-address-error",
            },
            classes=ClassMap(
                blocks={
                    "site-nav": "topbar-nav",
                    "badge": "cart-pip",
                    "auth-modal": "login-dialog",
                    "account-dropdown": "profile-menu",
                    "chat-widget": "concierge-panel",
                    "chat-launcher": "concierge-button",
                    "chat-message": "concierge-bubble",
                    "flash": "notice",
                    "hero__search": "masthead-search",
                    "search-results": "finder-panel",
                    "product-grid": "tile-rack",
                    "product-card": "product-tile",
                    "product-hero": "item-showcase",
                    "cart-item": "bag-row",
                    "cart-summary": "bag-totals",
                    "checkout-form": "payment-form",
                    "checkout-summary": "payment-totals",
                    "checkout-alert": "payment-notice",
                },
            ),
            layout={
                "product-card": "wrapped",
                "product-hero-actions": "wrapped",
                "checkout-field": "grouped",
            },
        ),
    }
)


# ---------------------------------------------------------------------------
# The template helpers (design Decision 1)
# ---------------------------------------------------------------------------

#: Where the per-stage stylesheet variants are served from (design Decision 5).
#: ``main.py`` mounts the small Starlette app of :func:`build_assets_app` here.
ASSETS_MOUNT_PATH: Final[str] = "/assets"


@dataclass(frozen=True)
class DriftView:
    """The drift hooks of one stage, as templates see them (``drift``).

    Every method takes a *stage-1* name and answers with the name this stage
    renders. Unknown names raise :class:`UnknownHook`, so a typo fails the
    contract tests instead of quietly never drifting.
    """

    stage: int

    def __post_init__(self) -> None:
        if self.stage not in STAGE_SPECS:
            raise ValueError(f"unknown locator stage: {self.stage!r}")

    @property
    def spec(self) -> StageSpec:
        """The mapping of this stage."""
        return STAGE_SPECS[self.stage]

    def id(self, key: str) -> str:
        """The id this stage renders for the covered id ``key``."""
        if key not in COVERED_IDS:
            if key in STABLE_IDS:
                raise UnknownHook(
                    f"{key!r} is a stable id: write it literally, it never drifts"
                )
            raise UnknownHook(f"unknown covered id: {key!r}")
        return self.spec.ids.get(key, key)

    def cls(self, keys: str) -> str:
        """The class names this stage renders for the covered ``keys``.

        ``keys`` is the whitespace-separated list a ``class`` attribute would
        contain, for example ``drift.cls("product-card product-card--compact")``.
        Uncovered classes (``button``, ``form-field``, ``is-*``) stay literal in
        the template and must not be passed here.
        """
        return " ".join(self._resolve_class(token) for token in keys.split())

    def _resolve_class(self, token: str) -> str:
        if not is_covered_class(token):
            raise UnknownHook(f"unknown covered class: {token!r}")
        classes = self.spec.classes
        if token in classes.exact:
            return classes.exact[token]
        if token in classes.blocks:
            return classes.blocks[token]
        block, suffix = split_class_token(token)
        if suffix and block in classes.blocks:
            return f"{classes.blocks[block]}{suffix}"
        return token

    def test(self, key: str) -> Markup:
        """The ``data-test`` attribute markup, or nothing in stages 3 and 4."""
        if key not in DATA_TEST_VALUES:
            raise UnknownHook(f"unknown data-test value: {key!r}")
        if not self.spec.keep_data_test:
            return Markup("")
        return Markup(f'data-test="{key}"')

    def layout(self, component: str) -> str:
        """The structural variant of ``component``, or ``""`` when it has none."""
        if component not in LAYOUT_COMPONENTS:
            raise UnknownHook(f"unknown layout component: {component!r}")
        return self.spec.layout.get(component, "")

    @property
    def stylesheet_href(self) -> str:
        """The stylesheet this stage links (design Decision 5).

        One variant per distinct class mapping, built at startup and served
        from ``/assets/styles.<digest>.css``. A page and its stylesheet always
        come from the same stage, even when the preset changes between the two
        requests, because the href carries the content digest.
        """
        return stylesheet_variant(self.stage).href


# ---------------------------------------------------------------------------
# The stylesheet follows the drift (design Decision 5)
# ---------------------------------------------------------------------------

#: The single stylesheet source. It lives outside ``static/`` so that no stage
#: can be read off a public file: only the rewritten variants are served.
STYLESHEET_SOURCE: Final[Path] = Path(__file__).resolve().parents[1] / "assets" / "styles.css"

#: ``Cache-Control`` of a variant. The href carries a content digest, so a
#: variant can be cached forever; a different stage links a different URL.
STYLESHEET_CACHE_CONTROL: Final[str] = "public, max-age=31536000, immutable"

#: A class token as it appears in a selector: the dot plus a CSS identifier.
_CLASS_SELECTOR = re.compile(r"\.(-?[_a-zA-Z][-_a-zA-Z0-9]*)")

#: A comment, so a prelude can be read without the comments in front of it.
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _is_at_rule(prelude: str) -> bool:
    """Whether ``prelude`` introduces an at-rule rather than a style rule.

    The comments a prelude may start with are ignored: a rule commented above
    ``@media`` must not turn the media block into a declaration block.
    """
    return _CSS_COMMENT.sub("", prelude).lstrip().startswith("@")


def _skip_string(text: str, start: int) -> int:
    """The index just past the quoted string that starts at ``start``."""
    quote = text[start]
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            return index + 1
        index += 1
    return index


def rewrite_selectors(prelude: str, drift: DriftView) -> str:
    """Rename the covered class tokens of one selector prelude.

    Only whole class tokens are replaced, so an uncovered name that merely
    contains a covered one (``category-badge``, ``site-nav-open``) is left
    alone, and so are element names, ``*``, attribute selectors and
    pseudo-classes. Quoted strings inside attribute selectors are copied
    verbatim.
    """
    pieces: list[str] = []
    index = 0
    while index < len(prelude):
        char = prelude[index]
        if char in "\"'":
            end = _skip_string(prelude, index)
            pieces.append(prelude[index:end])
            index = end
            continue
        if char == ".":
            match = _CLASS_SELECTOR.match(prelude, index)
            if match:
                token = match.group(1)
                pieces.append("." + (drift.cls(token) if is_covered_class(token) else token))
                index = match.end()
                continue
        pieces.append(char)
        index += 1
    return "".join(pieces)


def rewrite_stylesheet(css: str, drift: DriftView) -> str:
    """``css`` with every covered class token renamed for ``drift``'s stage.

    The rewrite touches selector preludes only. At-rule preludes
    (``@media (max-width: 40.5em)``), declaration blocks (``margin: .5rem``),
    comments and strings are copied byte for byte, so a value that looks like a
    class name never changes. Nested rules inside an at-rule block are rewritten
    like top-level rules.
    """
    out: list[str] = []
    pending: list[str] = []
    # One entry per open block: True while its content is further rules (an
    # at-rule block), False while it is declarations.
    blocks: list[bool] = []
    index = 0
    while index < len(css):
        char = css[index]
        if char == "/" and css.startswith("/*", index):
            end = css.find("*/", index + 2)
            end = len(css) if end == -1 else end + 2
            pending.append(css[index:end])
            index = end
            continue
        if char in "\"'":
            end = _skip_string(css, index)
            pending.append(css[index:end])
            index = end
            continue
        in_declarations = bool(blocks) and not blocks[-1]
        if char == "{" and not in_declarations:
            prelude = "".join(pending)
            pending = []
            at_rule = _is_at_rule(prelude)
            out.append(prelude if at_rule else rewrite_selectors(prelude, drift))
            out.append("{")
            blocks.append(at_rule)
            index += 1
            continue
        if char == "}":
            out.append("".join(pending))
            pending = []
            out.append("}")
            if blocks:
                blocks.pop()
            index += 1
            continue
        pending.append(char)
        index += 1
    out.append("".join(pending))
    return "".join(out)


@dataclass(frozen=True)
class StylesheetVariant:
    """One rewritten stylesheet, addressed by the digest of its content."""

    digest: str
    css: str

    @property
    def href(self) -> str:
        """The URL a page links this variant from."""
        return f"{ASSETS_MOUNT_PATH}/styles.{self.digest}.css"


def build_stylesheet_variants(css: str) -> Mapping[int, StylesheetVariant]:
    """One variant per stage, sharing an object per distinct class mapping.

    Stages 1 and 3 rename no class at all, so they rewrite to the same bytes
    and therefore to the same digest and the same URL.
    """
    variants: dict[int, StylesheetVariant] = {}
    by_content: dict[str, StylesheetVariant] = {}
    for stage in STAGES:
        rewritten = rewrite_stylesheet(css, DriftView(stage))
        variant = by_content.get(rewritten)
        if variant is None:
            digest = hashlib.sha256(rewritten.encode("utf-8")).hexdigest()[:16]
            variant = StylesheetVariant(digest=digest, css=rewritten)
            by_content[rewritten] = variant
        variants[stage] = variant
    return MappingProxyType(variants)


#: The variants, built once at import time - that is at startup, before the
#: first request - and kept in memory. Nothing is written to disk.
STYLESHEET_VARIANTS: Final[Mapping[int, StylesheetVariant]] = build_stylesheet_variants(
    STYLESHEET_SOURCE.read_text(encoding="utf-8")
)

#: The same variants by digest, which is how the mount looks one up.
STYLESHEET_BY_DIGEST: Final[Mapping[str, StylesheetVariant]] = MappingProxyType(
    {variant.digest: variant for variant in STYLESHEET_VARIANTS.values()}
)


def stylesheet_variant(stage: int) -> StylesheetVariant:
    """The stylesheet variant of ``stage``."""
    if stage not in STYLESHEET_VARIANTS:
        raise ValueError(f"unknown locator stage: {stage!r}")
    return STYLESHEET_VARIANTS[stage]


async def serve_stylesheet(request: Request) -> Response:
    """Serve one variant from memory, or 404 for an unknown digest."""
    variant = STYLESHEET_BY_DIGEST.get(request.path_params["digest"])
    if variant is None:
        return PlainTextResponse("Not Found", status_code=404)
    return Response(
        variant.css,
        media_type="text/css",
        headers={"Cache-Control": STYLESHEET_CACHE_CONTROL},
    )


def build_assets_app() -> Starlette:
    """The app ``main.py`` mounts at ``/assets`` (design Decision 5).

    A mount, not a FastAPI route: it is never listed in ``/openapi.json`` and
    it does not run the application-level dependencies, so the stylesheet stays
    outside the space resolution of ``workshop-spaces`` exactly like
    ``/static`` does.
    """
    return Starlette(routes=[Route("/styles.{digest}.css", serve_stylesheet)])


# ---------------------------------------------------------------------------
# The planted-bug registry (design Decision 9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlantedBug:
    """One registered defect.

    ``flow``, ``trigger`` and ``defect`` are the prose of the ``## Planted
    bugs`` table in ``docs/WORKSHOP-FEATURES.md`` and are compared with it by
    the docs-sync test. ``scope`` is the machine-readable surface the bug acts
    on, which is what ``planted_delay(scope)`` is parametrised with.
    """

    flag: str
    flow: str
    trigger: str
    defect: str
    scope: str

    @property
    def seed_description(self) -> str:
        """The ``feature_flags.description`` of this bug's seeded row.

        The backticks of the docs wording are dropped: the description is shown
        as plain text by the flag administration, not rendered as Markdown.
        """
        return f"Bug ({self.flow}): {self.defect}".replace("`", "")


#: Every planted bug, in registry order. That order is the order of the status
#: endpoint's ``active_bugs`` and of the docs table.
PLANTED_BUGS: Final[tuple[PlantedBug, ...]] = (
    PlantedBug(
        flag="BUG_MISSING_BUTTON",
        flow="Catalogue",
        trigger="product id % 5 == 0",
        defect="card has no add-to-cart button",
        scope="catalogue",
    ),
    PlantedBug(
        flag="BUG_WRONG_PRICE",
        flow="Catalogue",
        trigger="product id % 3 == 0",
        defect="card price × 1.15, rounded to cents",
        scope="catalogue",
    ),
    PlantedBug(
        flag="BUG_BROKEN_LINKS",
        flow="Catalogue",
        trigger="product id % 4 == 0",
        defect="card links to `/products/invalid-<id>`, which is not a product page (4xx)",
        scope="catalogue",
    ),
    PlantedBug(
        flag="BUG_SLOW_RESPONSE",
        flow="Catalogue",
        trigger="every request to `GET /products` or `GET /api/products/`",
        defect="1 to 3 s delay",
        scope="catalogue",
    ),
    PlantedBug(
        flag="BUG_CHECKOUT_TOTAL",
        flow="Checkout",
        trigger="any non-empty cart",
        defect="displayed total omits tax",
        scope="checkout",
    ),
)

#: The registered bug flags, in registry order.
BUG_FLAGS: Final[tuple[str, ...]] = tuple(bug.flag for bug in PLANTED_BUGS)

#: Price multiplier of ``BUG_WRONG_PRICE``.
WRONG_PRICE_FACTOR: Final[float] = 1.15


def _product_field(product: Any, name: str) -> Any:
    """Read ``name`` off a product dict or a product object."""
    if isinstance(product, Mapping):
        return product[name]
    return getattr(product, name)


@dataclass(frozen=True)
class BugView:
    """The planted bugs of one request, as templates and routes see them.

    The triggers depend only on the product id or on the cart, never on the
    stage, the session or the space, which is what makes the spec's "identical
    in every stage" property true by construction.
    """

    #: The registered bug flags that are enabled for this request.
    active: frozenset[str] = frozenset()

    @classmethod
    def from_flags(cls, flags: Mapping[str, bool]) -> BugView:
        """The bugs ``flags`` enables, ignoring every non-registry key."""
        return cls(active=frozenset(flag for flag in BUG_FLAGS if flags.get(flag)))

    def is_active(self, flag: str) -> bool:
        """Whether the registered bug ``flag`` is enabled for this request."""
        if flag not in BUG_FLAGS:
            raise UnknownHook(f"unknown planted bug: {flag!r}")
        return flag in self.active

    def card_price(self, product: Any) -> float:
        """The price a product card shows (``BUG_WRONG_PRICE``)."""
        price = float(_product_field(product, "price"))
        if self.is_active("BUG_WRONG_PRICE") and int(_product_field(product, "id")) % 3 == 0:
            return round(price * WRONG_PRICE_FACTOR, 2)
        return price

    def card_href(self, product: Any) -> str:
        """The product page a card links to (``BUG_BROKEN_LINKS``)."""
        product_id = int(_product_field(product, "id"))
        if self.is_active("BUG_BROKEN_LINKS") and product_id % 4 == 0:
            return f"/products/invalid-{product_id}"
        return f"/products/{product_id}"

    def hides_add_to_cart(self, product: Any) -> bool:
        """Whether a card renders no add-to-cart button (``BUG_MISSING_BUTTON``)."""
        if not self.is_active("BUG_MISSING_BUTTON"):
            return False
        return int(_product_field(product, "id")) % 5 == 0

    def checkout_total(self, summary: Mapping[str, Any]) -> dict[str, Any]:
        """The checkout summary as the page shows it (``BUG_CHECKOUT_TOTAL``).

        Returns a copy in which only ``total`` is replaced by ``subtotal``, so
        the subtotal and tax lines stay correct and the created order and its
        invoice are untouched (design Decision 10).
        """
        shown = dict(summary)
        if self.is_active("BUG_CHECKOUT_TOTAL"):
            shown["total"] = shown["subtotal"]
        return shown


#: The delay ``BUG_SLOW_RESPONSE`` adds, in seconds (design Decision 11). The
#: duration is random; what the registry makes deterministic is *which*
#: responses are delayed.
SLOW_RESPONSE_DELAY: Final[tuple[float, float]] = (1.0, 3.0)

#: The registered bug whose defect is a delay. Read from the registry, so the
#: scope :func:`planted_delay` accepts can never disagree with the docs table.
_DELAYING_BUG: Final[PlantedBug] = next(
    bug for bug in PLANTED_BUGS if bug.flag == "BUG_SLOW_RESPONSE"
)


def planted_delay(scope: str) -> Callable[..., Awaitable[None]]:
    """The dependency that delays the routes of ``scope`` (design Decision 11).

    ``planted_delay("catalogue")`` is attached to the two catalogue routes the
    registry names - the ``/products`` page and ``GET /api/products/`` - and to
    nothing else, so no other response is delayed. The sleep happens after
    ``get_effective_flags`` has resolved and before the route's own catalogue
    queries run, and it is an ``await``, so it never blocks the worker or
    another space on the same instance.

    Raises:
        UnknownHook: for a scope no delaying bug is registered for. A typo
            would otherwise install a dependency that can never fire.
    """
    if scope != _DELAYING_BUG.scope:
        raise UnknownHook(f"no delaying bug is registered for scope {scope!r}")

    async def delay(flags: dict[str, bool] = Depends(get_effective_flags)) -> None:
        if flags.get(_DELAYING_BUG.flag):
            await asyncio.sleep(random.uniform(*SLOW_RESPONSE_DELAY))

    return delay


# ---------------------------------------------------------------------------
# The request-scoped view and its Jinja globals (design Decision 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkshopView:
    """Everything one request needs in order to render drift and bugs."""

    stage: int
    drift: DriftView
    bugs: BugView

    @classmethod
    def from_flags(cls, flags: Mapping[str, bool]) -> WorkshopView:
        """Build the view of a request from its effective flags."""
        stage = effective_stage(flags)
        return cls(stage=stage, drift=DriftView(stage), bugs=BugView.from_flags(flags))


#: The view of the request being handled, set by :func:`workshop_view`.
_current_view: ContextVar[WorkshopView | None] = ContextVar("workshop_view", default=None)

#: ``request.state`` attribute that also holds the view of the request.
VIEW_STATE_ATTR: Final[str] = "workshop_view"


def current_workshop_view() -> WorkshopView:
    """The view of the request being handled.

    Raises:
        RuntimeError: when no view is set, that is when HTML is rendered outside
            a route that declares :func:`workshop_view` - from a global
            exception handler, say. An error or validation page is rendered by
            the route itself, after it has validated its input (design
            Decision 1).
    """
    view = _current_view.get()
    if view is None:
        raise RuntimeError(
            "No workshop view is active. `drift` and `bugs` are available only "
            "while a route that declares the `workshop_view` dependency is "
            "handling the request."
        )
    return view


class _ViewProxy:
    """Jinja global that forwards to one attribute of the current view.

    Registered once at startup and shared by every request; the object it
    forwards to comes from the :class:`~contextvars.ContextVar`, so macros
    imported without context still see the stage of the current request.
    """

    __slots__ = ("_attribute",)

    def __init__(self, attribute: str) -> None:
        self._attribute = attribute

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            # Let Python's own protocol lookups fail the normal way.
            raise AttributeError(name)
        return getattr(getattr(current_workshop_view(), self._attribute), name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<workshop {self._attribute} proxy>"


#: The Jinja global ``drift``: the :class:`DriftView` of the current request.
drift_global: Final[_ViewProxy] = _ViewProxy("drift")

#: The Jinja global ``bugs``: the :class:`BugView` of the current request.
bugs_global: Final[_ViewProxy] = _ViewProxy("bugs")


async def workshop_view(
    request: Request,
    flags: dict[str, bool] = Depends(get_effective_flags),
) -> AsyncIterator[WorkshopView]:
    """FastAPI dependency: the workshop view of this request.

    Stores the view on ``request.state.workshop_view`` and publishes it in the
    :class:`~contextvars.ContextVar` that the ``drift`` and ``bugs`` globals
    read, for the duration of the request only. The reset in ``finally`` is what
    makes those globals raise outside a request.
    """
    view = WorkshopView.from_flags(flags)
    setattr(request.state, VIEW_STATE_ATTR, view)
    token = _current_view.set(view)
    try:
        yield view
    finally:
        _current_view.reset(token)


# ---------------------------------------------------------------------------
# Presets (design Decision 12)
# ---------------------------------------------------------------------------

#: The AI flags. Preset ``clean`` turns on exactly ``AI_DETERMINISTIC``.
AI_FLAGS: Final[tuple[str, ...]] = (
    "AI_DETERMINISTIC",
    "AI_RANDOM_DELAYS",
    "AI_VARIED_RESPONSES",
)


def build_presets() -> dict[str, dict[str, bool]]:
    """The workshop presets, derived from the registries (design Decision 12).

    Presets are *absolute for the flag groups they own*: a preset writes every
    flag of a group it owns, so its result never depends on what ran before it,
    and it leaves the other groups alone, so presets compose (``stage3`` then
    ``buggy``). ``stage1`` therefore no longer clears the bugs; ``clean`` is the
    only preset that owns all three groups.
    """
    locator_off = {flag: False for flag in LOCATOR_FLAGS}
    bugs_off = {flag: False for flag in BUG_FLAGS}
    ai_clean = {flag: flag == "AI_DETERMINISTIC" for flag in AI_FLAGS}

    presets: dict[str, dict[str, bool]] = {
        "clean": {**locator_off, **bugs_off, **ai_clean},
        "stage1": dict(locator_off),
    }
    for stage in STAGES[1:]:
        presets[f"stage{stage}"] = {**locator_off, LOCATOR_FLAG_BY_STAGE[stage]: True}
    presets["buggy"] = {flag: True for flag in BUG_FLAGS}
    presets["drift_and_bug"] = {
        **locator_off,
        "LOCATOR_V4": True,
        **bugs_off,
        "BUG_WRONG_PRICE": True,
        "BUG_CHECKOUT_TOTAL": True,
    }
    presets["ai_chaos"] = {
        "AI_DETERMINISTIC": False,
        "AI_RANDOM_DELAYS": True,
        "AI_VARIED_RESPONSES": True,
    }
    return presets


# ---------------------------------------------------------------------------
# AI response variation (unchanged by this change)
# ---------------------------------------------------------------------------

AI_RESPONSE_VARIATIONS = [
    "Based on your query, I recommend checking out our {product}.",
    "Great question! The {product} might be exactly what you're looking for.",
    "I'd suggest taking a look at the {product} - it's quite popular!",
    "For your needs, the {product} could be a perfect fit.",
    "Have you considered the {product}? It has excellent reviews.",
]


def get_ai_response_template(flags: Mapping[str, bool], index: int = 0) -> str:
    """Get AI response template based on variation settings."""
    if flags.get("AI_VARIED_RESPONSES"):
        # Use different template based on index
        return AI_RESPONSE_VARIATIONS[index % len(AI_RESPONSE_VARIATIONS)]
    return AI_RESPONSE_VARIATIONS[0]


async def apply_ai_random_delay(flags: Mapping[str, bool]) -> None:
    """Add random delay to AI responses if enabled."""
    if flags.get("AI_RANDOM_DELAYS"):
        delay = random.uniform(0.5, 2.0)
        await asyncio.sleep(delay)
