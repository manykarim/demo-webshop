"""Smoke-test a running Demo Webshop container over HTTP.

The script is deliberately **standard library only** so it runs against any
container from a bare CI runner without installing anything: it is the same
script the ``smoke`` job of ``.github/workflows/image.yml`` runs on both
architectures (design D7).

It verifies one container in three phases, run as three separate invocations:

``fresh``
    A brand-new container: home page, ``/health`` and ``/api/workshop/status``
    version, the seeded catalogue, the demo login with its order history, the
    lazily rendered documents of every seeded order, and a full add-to-cart /
    checkout round trip including the runtime order's documents and the 404 for
    the static URL that must never serve order documents.
``restarted``
    The same container after ``docker restart``: seeding did not duplicate or
    refresh anything and the runtime order survived.
``recreated``
    A new container from the same image without a persisted data store: only
    seeded data is present, so the previous container's runtime order is gone.

The phases share a small state file, whose default lives in the system
temporary directory (never in the repository, where it would show up in the
build context probed by design D9). ``fresh`` writes it, the other two phases
read it and refuse to run without a matching one, so a stale or missing state
file fails the run instead of silently skipping the runtime-order assertions.

Every failing check exits non-zero and names itself, for example::

    FAIL [runtime-invoice] expected status 200, got 404
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

#: Seconds any single HTTP request may take. Generous because the first request
#: for a seeded order's document renders it on demand (design D8).
TIMEOUT = 60.0

#: The catalogue the seed data installs (design D4).
EXPECTED_PRODUCT_COUNT = 12

DEMO_EMAIL = "jamie@flowlinesupply.com"
DEMO_PASSWORD = "demo123"

DEFAULT_BASE_URL = "http://localhost:9090"
DEFAULT_EXPECT_VERSION = "dev"

#: One fixed path outside the repository, so the three phases of one container
#: share a state file without any caller naming it.
DEFAULT_STATE_FILE = str(Path(tempfile.gettempdir()) / "demo-webshop-smoke-state.json")


class CheckFailed(Exception):
    """A named check failed; the name is reported and the run exits non-zero."""

    def __init__(self, check: str, message: str) -> None:
        super().__init__(f"[{check}] {message}")
        self.check = check
        self.message = message


class Response:
    """The parts of an HTTP response the checks look at."""

    def __init__(self, status: int, headers: Any, body: bytes) -> None:
        self.status = status
        # Header names are case insensitive and uvicorn sends them lower case,
        # so they are normalised once instead of being looked up verbatim.
        self.headers = {name.lower(): value for name, value in headers.items()}
        self.body = body

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")

    def json(self, check: str) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CheckFailed(check, f"response body is not JSON: {exc}") from exc

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


def request(
    check: str,
    method: str,
    url: str,
    *,
    payload: Any | None = None,
    headers: dict[str, str] | None = None,
) -> Response:
    """Perform one HTTP request, turning transport errors into check failures."""
    data = None
    request_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            return Response(response.status, response.headers, response.read())
    except urllib.error.HTTPError as exc:
        # A 404 or 503 is a result, not a transport problem: the checks decide.
        return Response(exc.code, exc.headers, exc.read())
    except urllib.error.URLError as exc:
        raise CheckFailed(check, f"cannot reach {method} {url}: {exc.reason}") from exc
    except OSError as exc:  # e.g. a socket timeout surfacing outside URLError
        raise CheckFailed(check, f"cannot reach {method} {url}: {exc}") from exc


def expect_status(check: str, response: Response, expected: int, url: str) -> Response:
    if response.status != expected:
        raise CheckFailed(
            check,
            f"{url}: expected status {expected}, got {response.status}",
        )
    return response


def expect_pdf(check: str, response: Response, url: str) -> None:
    """A document endpoint must answer 200, ``application/pdf`` and a real PDF."""
    expect_status(check, response, 200, url)
    if not response.content_type.startswith("application/pdf"):
        raise CheckFailed(
            check,
            f"{url}: expected content type application/pdf, got {response.content_type!r}",
        )
    if not response.body.startswith(b"%PDF"):
        raise CheckFailed(
            check,
            f"{url}: body does not start with %PDF (first bytes: {response.body[:16]!r})",
        )


def report(message: str) -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------- #
# Shared checks
# --------------------------------------------------------------------------- #


def check_products(base_url: str) -> list[dict]:
    """The seeded catalogue is present exactly once."""
    check = "product-count"
    url = f"{base_url}/api/products/"
    response = expect_status(check, request(check, "GET", url), 200, url)
    payload = response.json(check)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise CheckFailed(check, f"{url}: response has no 'items' list")
    if len(items) != EXPECTED_PRODUCT_COUNT:
        raise CheckFailed(
            check,
            f"{url}: expected {EXPECTED_PRODUCT_COUNT} products, got {len(items)}",
        )
    report(f"ok   [{check}] {len(items)} products")
    return items


def check_login(base_url: str, check: str = "demo-login") -> list[dict]:
    """The demo user exists and carries its seeded order history."""
    url = f"{base_url}/api/auth/login"
    response = request(
        check,
        "POST",
        url,
        payload={"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
    )
    expect_status(check, response, 200, url)
    payload = response.json(check)
    orders = payload.get("orders") if isinstance(payload, dict) else None
    if not isinstance(orders, list) or not orders:
        raise CheckFailed(check, f"{url}: demo user has no orders")
    report(f"ok   [{check}] {DEMO_EMAIL} with {len(orders)} orders")
    return orders


# --------------------------------------------------------------------------- #
# State file
# --------------------------------------------------------------------------- #


def write_state(state_path: Path, state: dict) -> None:
    check = "write-state"
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise CheckFailed(check, f"cannot write state file {state_path}: {exc}") from exc
    report(f"ok   [{check}] {state_path}")


def read_state(state_path: Path, base_url: str) -> dict:
    """Load the state written by this container's ``fresh`` run.

    A missing, unreadable or foreign state file fails the run: without this
    guard the ``recreated`` phase's 404 check would pass for the wrong reason.
    """
    check = "state-file"
    if not state_path.exists():
        raise CheckFailed(
            check,
            f"state file {state_path} is missing; run --phase fresh against this container first",
        )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckFailed(check, f"state file {state_path} is unreadable: {exc}") from exc
    if not isinstance(state, dict):
        raise CheckFailed(check, f"state file {state_path} does not contain an object")

    recorded = state.get("base_url")
    if recorded != base_url:
        raise CheckFailed(
            check,
            f"state file {state_path} was written for base URL {recorded!r}, not {base_url!r}",
        )
    for key in ("runtime_order_id", "seeded_order_numbers", "seeded_summary_url"):
        if key not in state:
            raise CheckFailed(check, f"state file {state_path} has no {key!r} entry")
    report(f"ok   [{check}] {state_path} (runtime order {state['runtime_order_id']})")
    return state


# --------------------------------------------------------------------------- #
# Phases
# --------------------------------------------------------------------------- #


def phase_fresh(base_url: str, expect_version: str, state_path: Path) -> None:
    check = "home-page"
    url = f"{base_url}/"
    response = expect_status(check, request(check, "GET", url), 200, url)
    if "Flowline Supply" not in response.text():
        raise CheckFailed(check, f"{url}: body does not contain 'Flowline Supply'")
    report(f"ok   [{check}] {url}")

    check = "health"
    url = f"{base_url}/health"
    response = expect_status(check, request(check, "GET", url), 200, url)
    expected_health = {"status": "ok", "version": expect_version}
    health = response.json(check)
    if health != expected_health:
        raise CheckFailed(check, f"{url}: expected {expected_health}, got {health}")
    report(f"ok   [{check}] {health}")

    check = "workshop-status"
    url = f"{base_url}/api/workshop/status"
    response = expect_status(check, request(check, "GET", url), 200, url)
    status = response.json(check)
    version = status.get("version") if isinstance(status, dict) else None
    if version != expect_version:
        raise CheckFailed(check, f"{url}: expected version {expect_version!r}, got {version!r}")
    report(f"ok   [{check}] version {version!r}")

    products = check_products(base_url)
    orders = check_login(base_url)

    # Every seeded order's documents, which are rendered on demand (design D8).
    check = "seeded-documents"
    for order in orders:
        for field in ("invoice_url", "summary_url"):
            path = order.get(field)
            if not path:
                raise CheckFailed(
                    check,
                    f"seeded order {order.get('order_number')} has no {field}",
                )
            url = f"{base_url}{path}"
            expect_pdf(check, request(check, "GET", url), url)
    report(f"ok   [{check}] {2 * len(orders)} documents of {len(orders)} seeded orders")

    # A runtime order through the API, in its own cart session.
    session_id = f"smoke-{uuid.uuid4().hex}"
    headers = {"X-Session-ID": session_id}

    check = "add-to-cart"
    product_id = products[0].get("id")
    if not product_id:
        raise CheckFailed(check, "first product has no id")
    url = f"{base_url}/api/cart/items"
    response = request(
        check,
        "POST",
        url,
        payload={"product_id": product_id, "quantity": 2},
        headers=headers,
    )
    expect_status(check, response, 200, url)
    report(f"ok   [{check}] product {product_id} in session {session_id}")

    check = "checkout"
    url = f"{base_url}/api/checkout/"
    response = request(
        check,
        "POST",
        url,
        payload={
            "name": "Smoke Tester",
            "email": "smoke@flowlinesupply.com",
            "address": "1 Smoke Street, 12345 Testville",
        },
        headers=headers,
    )
    expect_status(check, response, 200, url)
    payload = response.json(check)
    runtime_order = payload.get("order") if isinstance(payload, dict) else None
    if not isinstance(runtime_order, dict):
        raise CheckFailed(check, f"{url}: response has no 'order' object")
    runtime_order_id = runtime_order.get("id")
    runtime_order_number = runtime_order.get("order_number")
    if not runtime_order_id or not runtime_order_number:
        raise CheckFailed(check, f"{url}: order has no id or order_number")
    report(f"ok   [{check}] order {runtime_order_number} (id {runtime_order_id})")

    check = "runtime-documents"
    for document in ("invoice.pdf", "summary.pdf"):
        url = f"{base_url}/api/docs/orders/{runtime_order_id}/{document}"
        expect_pdf(check, request(check, "GET", url), url)
    report(f"ok   [{check}] invoice and summary of {runtime_order_number}")

    # The static mount must not serve order documents, even now that the
    # documents exist (requirement *Order documents in the container*).
    check = "static-pdf-404"
    url = f"{base_url}/static/pdfs/invoice_{runtime_order_number}.pdf"
    expect_status(check, request(check, "GET", url), 404, url)
    report(f"ok   [{check}] {url} -> 404")

    write_state(
        state_path,
        {
            "base_url": base_url,
            "runtime_order_id": runtime_order_id,
            "runtime_order_number": runtime_order_number,
            "seeded_order_numbers": [order.get("order_number") for order in orders],
            "seeded_summary_url": orders[0].get("summary_url"),
        },
    )


def phase_restarted(base_url: str, state_path: Path) -> None:
    state = read_state(state_path, base_url)

    check_products(base_url)
    orders = check_login(base_url)

    check = "seeded-order-numbers"
    numbers = [order.get("order_number") for order in orders]
    expected_numbers = state["seeded_order_numbers"]
    if numbers != expected_numbers:
        raise CheckFailed(
            check,
            f"seeded order numbers changed: expected {expected_numbers}, got {numbers}",
        )
    report(f"ok   [{check}] {len(numbers)} unchanged seeded orders")

    check = "runtime-invoice"
    url = f"{base_url}/api/docs/orders/{state['runtime_order_id']}/invoice.pdf"
    expect_status(check, request(check, "GET", url), 200, url)
    report(f"ok   [{check}] runtime order {state.get('runtime_order_number')} survived the restart")

    check = "seeded-summary"
    url = f"{base_url}{state['seeded_summary_url']}"
    expect_pdf(check, request(check, "GET", url), url)
    report(f"ok   [{check}] {url}")


def phase_recreated(base_url: str, state_path: Path) -> None:
    state = read_state(state_path, base_url)

    check_products(base_url)
    check_login(base_url)

    check = "runtime-order-gone"
    url = f"{base_url}/api/docs/orders/{state['runtime_order_id']}/invoice.pdf"
    expect_status(check, request(check, "GET", url), 404, url)
    report(f"ok   [{check}] order {state.get('runtime_order_number')} is not in the new container")


PHASES = ("fresh", "restarted", "recreated")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smoke_image.py",
        description="Smoke-test a running Demo Webshop container over HTTP.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"base URL of the running container (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--expect-version",
        default=DEFAULT_EXPECT_VERSION,
        help=f"version /health must report (default: {DEFAULT_EXPECT_VERSION})",
    )
    parser.add_argument(
        "--phase",
        choices=PHASES,
        required=True,
        help="which phase of the container's life to check",
    )
    parser.add_argument(
        "--state",
        default=DEFAULT_STATE_FILE,
        help=f"file the phases share (default: {DEFAULT_STATE_FILE})",
    )
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    state_path = Path(args.state)

    report(f"smoke: phase {args.phase} against {base_url}")
    try:
        if args.phase == "fresh":
            phase_fresh(base_url, args.expect_version, state_path)
        elif args.phase == "restarted":
            phase_restarted(base_url, state_path)
        else:
            phase_recreated(base_url, state_path)
    except CheckFailed as exc:
        print(f"FAIL [{exc.check}] {exc.message}", file=sys.stderr, flush=True)
        return 1

    report(f"smoke: phase {args.phase} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
