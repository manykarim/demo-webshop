"""Locust load test for the workshop spaces of the demo webshop (design D10).

Every simulated user owns one space (``load-001``, ``load-002``, ...) and one
``X-Session-ID``, and sends both on every request, so the run is a crowd of
participants working side by side rather than one shared shop. On top of the
load numbers the run is a *leakage* test: a user constantly compares what the
server reports with what it did itself, and records a Locust failure named
``leak:<check>`` when another space shows through.

Run it against a target that can render PDFs, which the ``leak:order`` check
needs - the published image and every deployment of it (see
``docs/COOLIFY-RUNBOOK.md``)::

    docker run --rm -d --name ws-load -p 9090:9090 demo-webshop:spaces
    uv run --group loadtest locust -f loadtest/locustfile.py --headless \
        -H http://localhost:9090 -u 3 -r 3 -t 60s --csv reports/run

Locust must stay a single process (no ``--processes``, no workers): the order
registry below lives in process memory and is what makes the cross-space order
check possible.
"""
from __future__ import annotations

import logging
import random
import re
import threading
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from locust import HttpUser, between, events, task
from locust.stats import RequestStats, StatsEntry

LOGGER = logging.getLogger("loadtest")

# --- names and constants -----------------------------------------------------

#: Headers every request of a user carries (workshop space and cart session).
SPACE_HEADER = "X-Workshop-Space"
SESSION_HEADER = "X-Session-ID"

#: Space ids are GitHub handles: ``load-001`` is a valid one.
SPACE_PREFIX = "load-"

#: Suffix that keeps deliberately delayed requests out of the p95 (design D10).
SLOW_BUG_SUFFIX = " [slow-bug]"
#: Name prefixes of the two synthetic groups: leak checks and page sub-resources.
LEAK_PREFIX = "leak:"
ASSET_PREFIX = "asset:"
#: ``request_type`` of the synthetic leak rows, so they never look like HTTP.
CHECK_REQUEST_TYPE = "CHECK"

#: The pass bar of the quitting hook (design D10 and the capacity requirement).
P95_LIMIT_MS = 1000

#: Fixed request names. Every page and API row in the report is one of these,
#: so a product id, an asset digest or a stage never creates a new row.
NAME_HOME = "/"
NAME_PRODUCTS = "/products"
NAME_PRODUCT_DETAIL = "/products/{id}"
NAME_CART = "/cart"
NAME_CHECKOUT = "POST /checkout"
NAME_API_PRODUCTS = "GET /api/products/"
NAME_API_CART = "GET /api/cart/"
NAME_API_CART_ADD = "POST /api/cart/items"
NAME_API_STATUS = "GET /api/workshop/status"
NAME_API_PRESET = "POST /api/workshop/preset"
NAME_API_PRESETS = "GET /api/workshop/presets"
NAME_ORDER_DOC_OWN = "order-doc:own"
NAME_ORDER_DOC_OTHER = "order-doc:other"

#: Presets every build offers; the users switch between them.
SWITCHABLE_PRESETS = ("stage1", "stage2", "stage3", "stage4", "buggy", "clean")
#: Presets used only when the target lists them (``drift-coverage`` adds this one).
OPTIONAL_PRESETS = ("drift_and_bug",)

#: The attribute of the space indicator in the layout (design D8).
INDICATOR_ATTRIBUTE = "data-workshop-space"

#: Link the checkout confirmation renders for the new order.
ORDER_DOC_PATTERN = re.compile(r"/api/docs/orders/(\d+)/invoice\.pdf")

#: Flags that decide the locator stage, in the server's own order.
LOCATOR_FLAG_STAGES = (("LOCATOR_V4", "v4"), ("LOCATOR_V3", "v3"), ("LOCATOR_V2", "v2"))
#: The flag whose planted delay is excluded from the p95.
SLOW_BUG_FLAG = "BUG_SLOW_RESPONSE"


# --- expected flag map helpers (reused by sequence_check.py) -----------------


def merge_preset_flags(expected: dict[str, bool], applied: dict[str, bool]) -> dict[str, bool]:
    """Merge the flags a preset applied into ``expected`` (design D10).

    Presets compose: keys a preset does not set keep their value, so ``buggy``
    after ``stage3`` leaves the stage at ``v3``. Only called for a preset call
    that answered 2xx.
    """
    expected.update({str(key): bool(value) for key, value in applied.items()})
    return expected


def expected_locator_stage(flags: dict[str, bool]) -> str:
    """The stage the server reports for ``flags``, derived from the flag map.

    Never derived from the last preset name, which composition would make wrong.
    """
    for flag, stage in LOCATOR_FLAG_STAGES:
        if flags.get(flag):
            return stage
    return "v1"


def slow_bug_active(flags: dict[str, bool]) -> bool:
    """Whether responses are deliberately delayed for this flag map."""
    return bool(flags.get(SLOW_BUG_FLAG))


def request_name(base_name: str, flags: dict[str, bool]) -> str:
    """The report name of a request that the slow bug may delay.

    Chosen *before* the request is sent, from the expected flag map, so the
    delayed requests of ``/products`` and ``GET /api/products/`` land in their
    own row and stay out of the p95.
    """
    return f"{base_name}{SLOW_BUG_SUFFIX}" if slow_bug_active(flags) else base_name


# --- page assets -------------------------------------------------------------


class _AssetCollector(HTMLParser):
    """Collect stylesheet, script and image references of a rendered page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.assets: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        if tag == "link":
            if "stylesheet" in attributes.get("rel", "").lower().split() and attributes.get("href"):
                self.assets.append(("stylesheet", attributes["href"]))
        elif tag == "script" and attributes.get("src"):
            self.assets.append(("script", attributes["src"]))
        elif tag == "img" and attributes.get("src"):
            self.assets.append(("image", attributes["src"]))


def same_origin_target(url: str, page_path: str, host: str) -> str | None:
    """The request path of ``url`` when it is on ``host``, else ``None``.

    Relative, root-relative and absolute references are all resolved against
    the page, so nothing about the asset layout is assumed: a digest in the
    stylesheet name (``/assets/styles.<digest>.css``) or a moved directory
    changes nothing here.
    """
    candidate = url.strip()
    if not candidate or candidate.startswith(("data:", "mailto:", "javascript:", "#")):
        return None
    base = urljoin(host or "", page_path)
    absolute = urlsplit(urljoin(base, candidate))
    origin = urlsplit(host or "")
    if (absolute.scheme, absolute.netloc) != (origin.scheme, origin.netloc):
        return None
    target = absolute.path or "/"
    return f"{target}?{absolute.query}" if absolute.query else target


def collect_assets(html: str, page_path: str, host: str) -> list[tuple[str, str]]:
    """Unique ``(kind, path)`` pairs of the same-origin assets of a page."""
    collector = _AssetCollector()
    collector.feed(html)
    seen: set[tuple[str, str]] = set()
    targets: list[tuple[str, str]] = []
    for kind, url in collector.assets:
        target = same_origin_target(url, page_path, host)
        if target is None or (kind, target) in seen:
            continue
        seen.add((kind, target))
        targets.append((kind, target))
    return targets


# --- catalogue ---------------------------------------------------------------


#: Keys under which a catalogue response may carry its list of products.
#: ``GET /api/products/`` answers ``{"items": [...], ...}`` today; the other
#: names keep the parser working if the envelope is ever renamed.
CATALOGUE_LIST_KEYS = ("items", "products", "results")


def catalogue_entries(payload: object) -> list:
    """The product entries of a catalogue response, whatever wraps them.

    A bare list is returned as is. Anything the parser does not recognise
    yields an empty list rather than the envelope itself, so a renamed key is
    visible as "no product ids" instead of turning every request into the
    hard-coded fallback product.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in CATALOGUE_LIST_KEYS:
            entries = payload.get(key)
            if isinstance(entries, list):
                return entries
    return []


# --- shared state ------------------------------------------------------------


class LeakDetected(Exception):
    """Failure message of a ``leak:`` row; never raised into user code."""


class OrderRegistry:
    """Latest order id per load space, shared by every user in the process.

    Locust runs as a single process, so one user can ask for the order document
    of another user's space, which must answer 404 (design D10).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: dict[str, int] = {}

    def record(self, space: str, order_id: int) -> None:
        with self._lock:
            self._latest[space] = order_id

    def order_of_another_space(self, space: str) -> tuple[str, int] | None:
        with self._lock:
            candidates = [(name, order) for name, order in self._latest.items() if name != space]
        return random.choice(candidates) if candidates else None

    def clear(self) -> None:
        with self._lock:
            self._latest.clear()


ORDERS = OrderRegistry()

#: 5xx responses seen in this run, counted by the listener below.
SERVER_ERRORS: Counter[str] = Counter()

_space_lock = threading.Lock()
_space_counter = 0


def next_space_id() -> str:
    """The next free load space (``load-001``, ``load-002``, ...)."""
    global _space_counter
    with _space_lock:
        _space_counter += 1
        return f"{SPACE_PREFIX}{_space_counter:03d}"


def report_leak(user: HttpUser, check: str, message: str) -> None:
    """Record a failed isolation check as the Locust failure ``leak:<check>``."""
    user.environment.events.request.fire(
        request_type=CHECK_REQUEST_TYPE,
        name=f"{LEAK_PREFIX}{check}",
        response_time=0,
        response_length=0,
        context={},
        exception=LeakDetected(message),
    )


def extract_order_id(html: str) -> int | None:
    """The order id of the invoice link on a checkout confirmation page."""
    match = ORDER_DOC_PATTERN.search(html)
    return int(match.group(1)) if match else None


# --- the user behaviour ------------------------------------------------------


class WorkshopSpaceUser(HttpUser):
    """Shared behaviour: one space, one session, and the isolation checks.

    ``abstract`` keeps Locust from running this class directly; the load test
    user below and ``sequence_check.py`` build their flows on it.
    """

    abstract = True
    wait_time = between(0.5, 2)

    space: str
    session_id: str
    expected_flags: dict[str, bool]
    expected_cart: dict[int, int]
    latest_order_id: int | None
    product_ids: list[int]
    available_presets: list[str]

    # -- set-up

    def on_start(self) -> None:
        self.claim_space()
        self.available_presets = self.load_presets()
        self.apply_preset("clean")
        self.fetch_catalogue()

    def claim_space(self) -> None:
        """Take the next space and a session id, and send both from now on."""
        self.space = next_space_id()
        self.session_id = f"{self.space}-{uuid4().hex[:8]}"
        self.client.headers.update({SPACE_HEADER: self.space, SESSION_HEADER: self.session_id})
        self.expected_flags = {}
        self.expected_cart = {}
        self.latest_order_id = None
        self.product_ids = []
        self.available_presets = list(SWITCHABLE_PRESETS)

    def load_presets(self) -> list[str]:
        """Read the preset listing once and keep the names this build offers."""
        listing: dict = {}
        with self.client.get(
            "/api/workshop/presets", name=NAME_API_PRESETS, catch_response=True
        ) as response:
            if not response.ok:
                response.failure(f"HTTP {response.status_code}")
                return list(SWITCHABLE_PRESETS)
            try:
                listing = response.json().get("presets", {})
            except ValueError:
                response.failure("preset listing is not JSON")
                return list(SWITCHABLE_PRESETS)
        names = [name for name in SWITCHABLE_PRESETS if name in listing]
        names += [name for name in OPTIONAL_PRESETS if name in listing]
        return names or list(SWITCHABLE_PRESETS)

    # -- building blocks

    def apply_preset(self, preset: str) -> bool:
        """Apply ``preset`` in this user's space and update the expected map."""
        with self.client.post(
            "/api/workshop/preset",
            json={"preset": preset},
            name=NAME_API_PRESET,
            catch_response=True,
        ) as response:
            if not response.ok:
                response.failure(f"HTTP {response.status_code}")
                return False
            try:
                body = response.json()
            except ValueError:
                response.failure("preset response is not JSON")
                return False
            if body.get("status") != "success":
                response.failure(f"preset {preset} rejected: {body.get('message', '')}")
                return False
            merge_preset_flags(self.expected_flags, body.get("applied_flags") or {})
        return True

    def get_page(self, path: str, name: str) -> str:
        """Request an HTML page and return its body (empty on an error status)."""
        with self.client.get(path, name=name, catch_response=True) as response:
            if not response.ok:
                response.failure(f"HTTP {response.status_code}")
                return ""
            return response.text

    def fetch_assets(self, html: str, page_path: str) -> None:
        """Fetch the page's stylesheets, scripts and images as a browser would."""
        for kind, target in collect_assets(html, page_path, self.host or ""):
            self.client.get(target, name=f"{ASSET_PREFIX}{kind}")

    def fetch_catalogue(self) -> None:
        """Plain catalogue API request; keeps the product ids for later tasks."""
        with self.client.get(
            "/api/products/",
            name=request_name(NAME_API_PRODUCTS, self.expected_flags),
            catch_response=True,
        ) as response:
            if not response.ok:
                response.failure(f"HTTP {response.status_code}")
                return
            try:
                payload = response.json()
            except ValueError:
                response.failure("catalogue is not JSON")
                return
        products = catalogue_entries(payload)
        ids = [int(item["id"]) for item in products if isinstance(item, dict) and "id" in item]
        if ids:
            self.product_ids = ids

    def pick_product(self) -> int:
        """A product id from the catalogue API, never one parsed out of a page.

        Product links carry the planted ``BUG_BROKEN_LINKS`` targets, which
        would turn a browsing task into a 404 generator.
        """
        if not self.product_ids:
            self.fetch_catalogue()
        return random.choice(self.product_ids) if self.product_ids else 1

    def add_item(self) -> bool:
        """Add one product through the cart API and remember it as expected."""
        product_id = self.pick_product()
        quantity = random.randint(1, 2)
        with self.client.post(
            "/api/cart/items",
            json={"product_id": product_id, "quantity": quantity},
            name=NAME_API_CART_ADD,
            catch_response=True,
        ) as response:
            if not response.ok:
                response.failure(f"HTTP {response.status_code}")
                return False
        self.expected_cart[product_id] = self.expected_cart.get(product_id, 0) + quantity
        return True

    def submit_checkout(self) -> None:
        """Submit the checkout form and take the order id off the confirmation.

        A 2xx answer means the order was created and ``clear_cart()`` emptied
        the very cart the adds filled, so the expected items are reset exactly
        then; a 400 leaves both the server cart and the expectation untouched.
        """
        form = {
            "name": f"Load Test {self.space}",
            "email": f"{self.session_id}@example.com",
            "address": f"1 Load Street, {self.space}, Test City",
        }
        with self.client.post(
            "/checkout", data=form, name=NAME_CHECKOUT, catch_response=True
        ) as response:
            if not response.ok:
                response.failure(f"HTTP {response.status_code}")
                return
            html = response.text
            order_id = extract_order_id(html)
            if order_id is None:
                response.failure("confirmation page without an invoice link")
        self.expected_cart.clear()
        if order_id is None:
            return
        self.check_indicator(html, NAME_CHECKOUT)
        self.latest_order_id = order_id
        ORDERS.record(self.space, order_id)
        self.check_orders()

    # -- isolation checks

    def check_indicator(self, html: str, page: str) -> None:
        """``leak:indicator``: the page shows this user's space, not another."""
        if not html:
            return
        if f'{INDICATOR_ATTRIBUTE}="{self.space}"' not in html:
            report_leak(
                self,
                "indicator",
                f'{page} does not carry {INDICATOR_ATTRIBUTE}="{self.space}"',
            )

    def check_status(self, expected_stage: str | None = None) -> dict | None:
        """``leak:space`` and ``leak:stage`` on the workshop status endpoint."""
        body: dict | None = None
        with self.client.get(
            "/api/workshop/status", name=NAME_API_STATUS, catch_response=True
        ) as response:
            if not response.ok:
                response.failure(f"HTTP {response.status_code}")
                return None
            try:
                body = response.json()
            except ValueError:
                response.failure("status is not JSON")
                return None
        if body.get("space") != self.space:
            report_leak(self, "space", f"status reports space {body.get('space')!r}")
        stage = expected_stage or expected_locator_stage(self.expected_flags)
        if body.get("locator_stage") != stage:
            report_leak(
                self,
                "stage",
                f"status reports stage {body.get('locator_stage')!r}, expected {stage!r}",
            )
        return body

    def check_cart(self) -> None:
        """``leak:cart``: the cart holds exactly what this user put in it."""
        with self.client.get("/api/cart/", name=NAME_API_CART, catch_response=True) as response:
            if not response.ok:
                response.failure(f"HTTP {response.status_code}")
                return
            try:
                body = response.json()
            except ValueError:
                response.failure("cart is not JSON")
                return
        actual = {
            int(item["product_id"]): int(item["quantity"]) for item in body.get("items", [])
        }
        if actual != self.expected_cart:
            report_leak(self, "cart", f"cart holds {actual}, expected {self.expected_cart}")

    def check_orders(self) -> None:
        """``leak:order``: own order document 200, another space's one 404.

        Armed only once this user has an order and the registry holds an order
        of another load space. Both requests carry this user's space header, so
        a 200 on the other space's invoice is a visibility leak, and anything
        but 200 on its own - a 503 where PDF rendering is unavailable - is one
        too.
        """
        if self.latest_order_id is None:
            return
        other = ORDERS.order_of_another_space(self.space)
        if other is None:
            return
        other_space, other_order_id = other
        with self.client.get(
            f"/api/docs/orders/{self.latest_order_id}/invoice.pdf",
            name=NAME_ORDER_DOC_OWN,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")
                report_leak(
                    self,
                    "order",
                    f"own invoice {self.latest_order_id} answered {response.status_code}",
                )
        with self.client.get(
            f"/api/docs/orders/{other_order_id}/invoice.pdf",
            name=NAME_ORDER_DOC_OTHER,
            catch_response=True,
        ) as response:
            if response.status_code == 404:
                response.success()
            else:
                response.failure(f"HTTP {response.status_code}")
                report_leak(
                    self,
                    "order",
                    f"invoice {other_order_id} of space {other_space} answered "
                    f"{response.status_code} in {self.space}",
                )


class WorkshopParticipant(WorkshopSpaceUser):
    """One participant working in its own space, as a test suite would."""

    @task(3)
    def home(self) -> None:
        html = self.get_page("/", NAME_HOME)
        self.check_indicator(html, NAME_HOME)
        self.fetch_assets(html, "/")

    @task(4)
    def catalogue_page(self) -> None:
        name = request_name(NAME_PRODUCTS, self.expected_flags)
        html = self.get_page("/products", name)
        self.check_indicator(html, name)
        self.fetch_assets(html, "/products")

    @task(3)
    def catalogue_api(self) -> None:
        self.fetch_catalogue()

    @task(3)
    def product_detail(self) -> None:
        html = self.get_page(f"/products/{self.pick_product()}", NAME_PRODUCT_DETAIL)
        self.check_indicator(html, NAME_PRODUCT_DETAIL)

    @task(3)
    def add_to_cart(self) -> None:
        self.add_item()

    @task(2)
    def cart(self) -> None:
        html = self.get_page("/cart", NAME_CART)
        self.check_indicator(html, NAME_CART)
        self.check_cart()

    @task(2)
    def checkout(self) -> None:
        # The cart must not be empty: an empty one answers 400 by design.
        self.add_item()
        self.submit_checkout()

    @task(2)
    def switch_preset(self) -> None:
        self.apply_preset(random.choice(self.available_presets))

    @task(2)
    def status(self) -> None:
        self.check_status()


# --- run verdict -------------------------------------------------------------


@events.request.add_listener
def _count_server_errors(name: str = "", response=None, **_kwargs) -> None:
    """Count 5xx answers; the quitting hook fails the run on any of them."""
    status = getattr(response, "status_code", None)
    if status is not None and status >= 500:
        SERVER_ERRORS[f"{name} -> HTTP {status}"] += 1


def counts_towards_p95(name: str) -> bool:
    """Whether a report row belongs to the HTML and API p95 (design D10)."""
    if name.startswith((LEAK_PREFIX, ASSET_PREFIX)):
        return False
    return SLOW_BUG_SUFFIX not in name


def aggregate_p95(stats: RequestStats) -> int | None:
    """p95 over the HTML and API rows, excluding the deliberately slow ones."""
    aggregate = StatsEntry(stats, "p95 of HTML and API requests", "AGGREGATE")
    counted = 0
    for entry in stats.entries.values():
        if not counts_towards_p95(entry.name):
            continue
        aggregate.extend(entry)
        counted += entry.num_requests
    return aggregate.get_response_time_percentile(0.95) if counted else None


def run_problems(stats: RequestStats) -> list[str]:
    """Everything that makes this run a failure, as human-readable lines."""
    problems: list[str] = []

    p95 = aggregate_p95(stats)
    if p95 is None:
        problems.append("no HTML or API requests were recorded")
    elif p95 >= P95_LIMIT_MS:
        problems.append(f"p95 of HTML and API requests is {p95} ms (limit {P95_LIMIT_MS} ms)")

    if SERVER_ERRORS:
        detail = ", ".join(f"{key} x{count}" for key, count in sorted(SERVER_ERRORS.items()))
        problems.append(f"{sum(SERVER_ERRORS.values())} server errors: {detail}")

    leaks = {
        entry.name: entry.num_failures
        for entry in stats.entries.values()
        if entry.name.startswith(LEAK_PREFIX) and entry.num_failures
    }
    if leaks:
        detail = ", ".join(f"{name} x{count}" for name, count in sorted(leaks.items()))
        problems.append(f"{sum(leaks.values())} isolation failures: {detail}")

    assets = {
        entry.name: entry.num_failures
        for entry in stats.entries.values()
        if entry.name.startswith(ASSET_PREFIX) and entry.num_failures
    }
    if assets:
        detail = ", ".join(f"{name} x{count}" for name, count in sorted(assets.items()))
        problems.append(f"{sum(assets.values())} failed asset requests: {detail}")

    return problems


@events.quitting.add_listener
def _set_exit_code(environment, **_kwargs) -> None:
    """Fail the run unless it is fast, error-free and free of leakage."""
    problems = run_problems(environment.stats)
    for problem in problems:
        LOGGER.error(f"FAIL: {problem}")
    if problems:
        environment.process_exit_code = 1
    else:
        p95 = aggregate_p95(environment.stats)
        LOGGER.info(
            f"PASS: p95 {p95} ms, no server errors, no leaks, no failed assets"
        )
        environment.process_exit_code = 0
