"""Suite conftest for the contract tests (drift-coverage Decision 7).

This file builds *only* on the shared harness of ``backend/tests/harness.py``
and the canonical fixtures of the root ``backend/tests/conftest.py``. It sets no
environment variable, patches no settings, resets no engine global, clears no
flag bookkeeping and defines no fixture called ``temp_database``,
``app_client``, ``seeded_app_client``, ``pdf_unavailable`` or
``fake_weasyprint``: ``isolated_app`` already does all of that, and the root
conftest pins the process environment before the application is imported for the
first time. The result therefore does not depend on pytest's collection order or
on another suite importing the app first.

``backend.app`` is imported only inside fixture bodies, so collecting this suite
does not import the application.

The suite fixtures are:

``contract_client``
    package-scoped ``TestClient`` on a private database with products and
    feature flags seeded (no users: contract tests need none).
``render``
    render a page in a given set of effective flags.
``rendered``
    ``rendered(page, stage, bugs=())``: the same render, memoized for the whole
    package, with the page's cart filled on first use. This is what the matrix
    is built on.
``add_to_cart``
    fill a cart through the public API.
``product_id_by_sku``
    the seeded product id of a SKU, so a test never hard-codes one.
``subprocess_env``
    an environment for a fresh interpreter that points at the same temporary
    database and PDF directory as ``contract_client``.

Every fixture except ``subprocess_env`` is package-scoped: none of them holds
per-test state, and the matrix renders each cell once.

Contract tests that place an order also request the root fixture
``fake_weasyprint``, so none of them needs native PDF libraries.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# The page matrix (drift-coverage Decision 7, "Matrix")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    """One entry of the contract matrix.

    ``key`` is the stable name the oracles refer to, ``path`` is what is
    requested (query string included) and ``cart`` is the cart the session must
    hold before the page is requested, as ``(sku, quantity)`` pairs.

    ``method``, ``form`` and ``status`` describe the rendered ``POST /checkout``
    results (task 14.1): the same page template, reached by submitting the
    checkout form with an empty cart (the 400 error render) and with items (the
    order confirmation). ``masked`` says that this render carries values that
    are unique per order and is therefore compared through
    ``semantic.ORDER_RESULT_MASK``; ``fresh_cart`` says that the render consumes
    its cart - the confirmation clears it - so every matrix cell fills a cart of
    its own instead of sharing one.
    """

    key: str
    path: str
    cart: tuple[tuple[str, int], ...] = ()
    #: Free-form notes for readers of the matrix; never used by a check.
    note: str = ""
    #: The HTTP method this render is requested with.
    method: str = "GET"
    #: The form body of a ``POST`` render, as ``(field, value)`` pairs.
    form: tuple[tuple[str, str], ...] = ()
    #: The status code this render must answer with.
    status: int = 200
    #: Whether comparing this render needs ``semantic.ORDER_RESULT_MASK``.
    masked: bool = False
    #: Whether the render consumes its cart, so each cell needs one of its own.
    fresh_cart: bool = False


#: The cart every cart and checkout cell is rendered with. One and the same in
#: every cell, so a difference between two cells can only come from the stage or
#: the bug set.
MATRIX_CART: tuple[tuple[str, int], ...] = (("PUL-RNG-003", 2), ("ATL-DSK-005", 1))

#: The form body every ``POST /checkout`` cell submits - identical in every
#: case, so two confirmations differ only in the order number and the order id
#: (``semantic.ORDER_RESULT_MASK``).
CHECKOUT_FORM: tuple[tuple[str, str], ...] = (
    ("name", "Jamie Product"),
    ("email", "jamie@flowlinesupply.com"),
    ("address", "123 Flow Street\nSan Francisco, CA"),
)

#: The form body of the rejected ``POST /checkout`` cell: every checked field is
#: invalid, so the render shows all three per-field messages
#: (acceptance-conformance, WEB-006_AC-4 to AC-6 and AC-11).
CHECKOUT_INVALID_FORM: tuple[tuple[str, str], ...] = (
    ("name", "A"),
    ("email", "a@b"),
    ("address", "123"),
)

#: Every page the contract matrix covers, in reading order. The oracles and the
#: stage checks are written against ``Page.key``, so adding a page needs no
#: change to them.
COVERED_PAGES: tuple[Page, ...] = (
    Page(key="home", path="/", note="hero search, featured product grids"),
    Page(key="listing", path="/products", note="listing, filter panel, cards"),
    Page(key="detail", path="/products/3", note="product hero, related cards"),
    Page(
        key="detail-not-found",
        path="/products/9999",
        note="an id that names no product: the HTML not-found render (WEB-003_AC-9)",
        status=404,
    ),
    Page(
        key="search-results",
        path="/search/results?query=desk",
        note="the fragment app.js inserts (Decision 6)",
    ),
    Page(key="cart-empty", path="/cart"),
    Page(key="cart-items", path="/cart", cart=MATRIX_CART),
    Page(key="checkout-empty", path="/checkout"),
    Page(key="checkout-items", path="/checkout", cart=MATRIX_CART),
    Page(
        key="checkout-post-empty",
        path="/checkout",
        note="POST /checkout with an empty cart: the 400 error render",
        method="POST",
        form=CHECKOUT_FORM,
        status=400,
    ),
    Page(
        key="checkout-post-invalid",
        path="/checkout",
        cart=MATRIX_CART,
        note="POST /checkout with invalid fields: the 422 render with per-field messages (WEB-006_AC-11)",
        method="POST",
        form=CHECKOUT_INVALID_FORM,
        status=422,
    ),
    Page(
        key="checkout-post-success",
        path="/checkout",
        cart=MATRIX_CART,
        note="POST /checkout with items: the order confirmation render",
        method="POST",
        form=CHECKOUT_FORM,
        masked=True,
        fresh_cart=True,
    ),
)

#: The pages by key, for the oracles and for readability in parametrizations.
PAGES_BY_KEY: Mapping[str, Page] = {page.key: page for page in COVERED_PAGES}

#: The effective flags that select each locator stage. Stage 1 is the absence of
#: every locator flag, which is why its entry is empty.
STAGE_FLAGS: Mapping[int, Mapping[str, bool]] = {
    1: {},
    2: {"LOCATOR_V2": True},
    3: {"LOCATOR_V3": True},
    4: {"LOCATOR_V4": True},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="package")
def contract_client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    """A ``TestClient`` on a private database, shared by the whole package.

    ``isolated_app`` seeds products and feature flags and no users, patches the
    settings and the engine globals for the duration and restores them
    afterwards. Nothing else is needed here.
    """
    from backend.tests.harness import isolated_app

    with isolated_app(tmp_path_factory.mktemp("contract")) as client:
        yield client


@dataclass(frozen=True)
class Renderer:
    """Render a page of the shop with a chosen set of effective flags.

    Calling the instance overrides the flag seam
    (``core.feature_flags.get_effective_flags``) for the duration of the single
    request and clears the override again in ``finally``, so a failing render
    cannot leak a stage into the next test. The override is the whole reason the
    matrix is fast: it needs neither the database nor the workshop endpoints,
    and it is independent of spaces.
    """

    client: Any

    def __call__(
        self,
        path: str,
        flags: Mapping[str, bool] | None = None,
        session_id: str | None = None,
        *,
        method: str = "GET",
        data: Mapping[str, Any] | None = None,
        follow_redirects: bool = False,
        extra_headers: Mapping[str, str] | None = None,
    ):
        from backend.app.core.feature_flags import get_effective_flags
        from backend.app.main import app

        resolved = {str(key).upper(): bool(value) for key, value in (flags or {}).items()}

        async def _effective_flags() -> dict[str, bool]:
            return dict(resolved)

        headers = {"x-session-id": session_id} if session_id else {}
        # ``X-Workshop-Space`` for the space checks of task 15.2: the flag seam
        # is overridden either way, so the header decides only which space the
        # application-level dependency resolves - and therefore what the layout
        # renders as the space indicator.
        headers.update({str(key): str(value) for key, value in (extra_headers or {}).items()})

        app.dependency_overrides[get_effective_flags] = _effective_flags
        try:
            return self.client.request(
                method,
                path,
                headers=headers,
                data=data,
                follow_redirects=follow_redirects,
            )
        finally:
            app.dependency_overrides.pop(get_effective_flags, None)


@pytest.fixture(scope="package")
def render(contract_client: TestClient) -> Renderer:
    """``render(path, flags, session_id)``: one page render in chosen flags."""
    return Renderer(client=contract_client)


@pytest.fixture(scope="package")
def product_id_by_sku(contract_client: TestClient) -> Callable[[str], int]:
    """``product_id_by_sku(sku)``: the seeded product id of a SKU.

    The mapping is read once from ``GET /api/products/`` and then served from
    memory, so a test never hard-codes an id and never pays for a second
    request.
    """
    cache: dict[str, int] = {}

    def lookup(sku: str) -> int:
        if not cache:
            response = contract_client.get("/api/products/")
            response.raise_for_status()
            cache.update(
                {str(item["sku"]): int(item["id"]) for item in response.json()["items"]}
            )
        try:
            return cache[sku]
        except KeyError:  # pragma: no cover - a typo in a test's SKU
            raise AssertionError(f"no seeded product with SKU {sku!r}") from None

    return lookup


@pytest.fixture(scope="package")
def add_to_cart(
    contract_client: TestClient, product_id_by_sku: Callable[[str], int]
) -> Callable[..., None]:
    """``add_to_cart(session_id, items)``: fill a cart through the public API.

    ``items`` are ``(sku, quantity)`` pairs, the same shape as ``Page.cart``.
    Carts are per session id, so every matrix cell can use a session of its own
    and no case depends on another one's leftovers.
    """

    def fill(session_id: str, items: Sequence[tuple[str, int]]) -> None:
        for sku, quantity in items:
            response = contract_client.post(
                "/api/cart/items",
                json={"product_id": product_id_by_sku(sku), "quantity": quantity},
                headers={"X-Session-ID": session_id},
            )
            assert response.status_code == 200, response.text

    return fill


@contextmanager
def zero_planted_delay() -> Iterator[None]:
    """Render with ``BUG_SLOW_RESPONSE`` planting a delay of zero seconds.

    ``planted_delay`` sleeps for ``random.uniform(*SLOW_RESPONSE_DELAY)``, and
    the module global is read on every call, so setting it to ``(0.0, 0.0)``
    turns the delay off without touching the dependency, the flag or
    ``asyncio.sleep``. The matrix renders ``/products`` in four stages with the
    bug on; at 1 to 3 seconds a cell that would be 8 to 24 seconds of sleeping.
    The real duration is asserted by ``test_planted_bugs.py``, which does not
    use this helper.
    """
    from backend.app.core import workshop

    previous = workshop.SLOW_RESPONSE_DELAY
    workshop.SLOW_RESPONSE_DELAY = (0.0, 0.0)  # type: ignore[misc]
    try:
        yield
    finally:
        workshop.SLOW_RESPONSE_DELAY = previous  # type: ignore[misc]


@pytest.fixture(scope="package")
def rendered(render: Renderer, add_to_cart: Callable[..., None]) -> Callable[..., str]:
    """``rendered(page, stage, bugs=())``: one matrix cell, rendered once.

    ``page`` is a :class:`Page`, ``stage`` a locator stage and ``bugs`` the
    planted-bug flags to switch on. Each page uses a session id of its own, so a
    cart is filled exactly once and no cell depends on another one's leftovers;
    a page whose render consumes its cart (``fresh_cart``) gets a session per
    cell instead, filled with the same items every time. The rendered HTML is
    kept for the whole package, which is what keeps the matrix - pages x stages
    x bug sets - cheap.

    ``planted_delay`` is neutralised for the whole matrix
    (:func:`zero_planted_delay`), so the ``buggy`` column costs no wall-clock
    time.

    A cell that places an order needs the root ``fake_weasyprint`` fixture to be
    active in the test that renders it first; the tests of the matrix request
    it.
    """
    html_by_cell: dict[tuple[str, int, tuple[str, ...]], str] = {}
    filled: set[str] = set()

    def get(page: Page, stage: int, bugs: Sequence[str] = ()) -> str:
        bug_flags = tuple(sorted(str(flag).upper() for flag in bugs))
        cell = (page.key, stage, bug_flags)
        if cell not in html_by_cell:
            session_id = f"contract-{page.key}"
            if page.fresh_cart:
                session_id = f"{session_id}-{stage}-{'-'.join(bug_flags) or 'clean'}"
            if page.cart and session_id not in filled:
                add_to_cart(session_id, page.cart)
                filled.add(session_id)
            flags = {**STAGE_FLAGS[stage], **dict.fromkeys(bug_flags, True)}
            with zero_planted_delay():
                response = render(
                    page.path,
                    flags,
                    session_id,
                    method=page.method,
                    data=dict(page.form) or None,
                )
            assert response.status_code == page.status, (
                f"{page.key} in stage {stage} with {bug_flags} returned "
                f"{response.status_code}, expected {page.status}: {response.text[:400]}"
            )
            html_by_cell[cell] = response.text
        return html_by_cell[cell]

    return get


@pytest.fixture(scope="package")
def subprocess_env(contract_client: TestClient) -> dict[str, str]:
    """The environment for a fresh interpreter that must see the same storage.

    A copy of ``os.environ`` in which ``WORKSHOP_DATABASE_URL`` and
    ``WORKSHOP_PDF_OUTPUT_DIR`` carry the values ``settings`` holds while
    ``contract_client`` is active, so a subprocess (the fresh-interpreter
    determinism check) writes into the same temporary directory instead of into
    the repository.
    """
    from backend.app.core.config import settings

    environment = dict(os.environ)
    environment["WORKSHOP_DATABASE_URL"] = settings.database_url
    environment["WORKSHOP_PDF_OUTPUT_DIR"] = str(settings.pdf_output_dir)
    return environment
