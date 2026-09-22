"""Forty spaces shop at the same time without locking each other out (task 10.2).

This is the test that would fail if SQLite were left on its rollback journal or
on SQLAlchemy's default pool of five connections (design D9), and the one that
would fail if a space were carried in anything shared between requests rather
than resolved per request (design D1).

Everything runs inside a *single* ``asyncio.run``: ``init_db()``, the seeding,
the forty concurrent clients and ``shutdown_db()``. A pooled ``aiosqlite``
connection belongs to the event loop that opened it, so a second loop would
report failures that have nothing to do with concurrency. For the same reason
the whole run happens once, in one test, and the checks below are helper
functions rather than separate test functions.

Each participant follows the workshop flow: apply a preset, add an item, check
out, and - because ``POST /api/checkout/`` clears the cart - add a second item,
so the space still owns a live cart row to compare against. The final status and
cart of every client must show that client's own actions and nothing else.

The checkouts render their documents through ``fake_weasyprint``. The subject
here is database contention, and forty *real* WeasyPrint renders saturate the
CPU of the machine running the tests, which starves the event loop for seconds
at a time and makes a writer exceed its busy timeout for a reason that has
nothing to do with SQLite. Rendering under load is measured by the Locust load
test instead (design D10).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.tests.spaces.helpers import sqlite_rows

#: Concurrent participants, the number the workshop is sized for (design D9).
PARTICIPANTS = 40

#: Requests each participant sends, in the order of :func:`shop`.
REQUESTS_PER_PARTICIPANT = 6

#: The message SQLite produces when a writer gives up waiting for the lock.
LOCKED_MESSAGE = "database is locked"

#: Preset per participant and the locator stage its status must report.
PRESET_STAGES: dict[str, str] = {"stage2": "v2", "stage3": "v3"}


@dataclass
class Participant:
    """One simulated participant and the answers its own requests produced."""

    index: int
    preset: str
    product_id: int
    quantity: int
    statuses: list[tuple[str, int]] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)
    failure: BaseException | None = None
    order_number: str = ""
    status: dict[str, Any] = field(default_factory=dict)
    cart: dict[str, Any] = field(default_factory=dict)

    @property
    def space(self) -> str:
        return f"load-{self.index:03d}"

    @property
    def session_id(self) -> str:
        return f"session-{self.index:03d}"

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Workshop-Space": self.space, "X-Session-ID": self.session_id}

    @property
    def expected_stage(self) -> str:
        return PRESET_STAGES[self.preset]


class LockWatcher(logging.Handler):
    """Records every log message that mentions a SQLite lock, from any logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.locked: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - a broken record is not our subject
            return
        text = f"{message} {record.exc_text or ''}"
        if LOCKED_MESSAGE in text.lower():
            self.locked.append(text)


# ---------------------------------------------------------------------------
# The concurrent run
# ---------------------------------------------------------------------------


async def shop(client, participant: Participant) -> None:
    """The workshop flow of one participant, all of it in its own space."""
    headers = participant.headers

    def record(response) -> None:
        participant.statuses.append((response.request.url.path, response.status_code))
        participant.bodies.append(response.text)

    response = await client.post(
        "/api/workshop/preset", json={"preset": participant.preset}, headers=headers
    )
    record(response)

    response = await client.post(
        "/api/cart/items",
        json={"product_id": participant.product_id, "quantity": participant.quantity},
        headers=headers,
    )
    record(response)

    response = await client.post(
        "/api/checkout/",
        json={
            "name": f"Participant {participant.index}",
            "email": f"participant{participant.index}@example.com",
            "address": f"{participant.index} Workshop Lane",
        },
        headers=headers,
    )
    record(response)
    if response.status_code == 200:
        participant.order_number = response.json()["order"]["order_number"]

    # The checkout emptied the cart, so the space gets a live row back before
    # the final read; without it every participant's cart would be empty and
    # the comparison below could not tell the spaces apart.
    response = await client.post(
        "/api/cart/items",
        json={"product_id": participant.product_id, "quantity": participant.quantity},
        headers=headers,
    )
    record(response)

    response = await client.get("/api/workshop/status", headers=headers)
    record(response)
    if response.status_code == 200:
        participant.status = response.json()

    response = await client.get("/api/cart/", headers=headers)
    record(response)
    if response.status_code == 200:
        participant.cart = response.json()


async def run_workshop() -> list[Participant]:
    """Seed a database and let :data:`PARTICIPANTS` spaces work on it at once."""
    import httpx

    from backend.app.core.db import get_session_factory, init_db, shutdown_db
    from backend.app.main import app
    from backend.app.seeds.seed_data import seed_feature_flags, seed_products

    await init_db()
    session_factory = get_session_factory()
    async with session_factory() as session:
        await seed_products(session)
        await seed_feature_flags(session)

    product_ids = [row[0] for row in sqlite_rows("SELECT id FROM products ORDER BY id")]
    assert product_ids, "the seeder must have produced products to shop for"

    presets = list(PRESET_STAGES)
    participants = [
        Participant(
            index=index,
            preset=presets[index % len(presets)],
            product_id=product_ids[index % len(product_ids)],
            quantity=1 + index % 3,
        )
        for index in range(1, PARTICIPANTS + 1)
    ]

    transport = httpx.ASGITransport(app=app)
    clients = [
        httpx.AsyncClient(transport=transport, base_url="http://workshop", timeout=120.0)
        for _ in participants
    ]
    try:
        # ``return_exceptions`` keeps one participant's failure from cancelling
        # the other thirty-nine, so the report names every space that broke.
        outcomes = await asyncio.gather(
            *(shop(client, participant) for client, participant in zip(clients, participants)),
            return_exceptions=True,
        )
        for participant, outcome in zip(participants, outcomes):
            if isinstance(outcome, BaseException):
                participant.failure = outcome
    finally:
        await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)
        await shutdown_db()

    return participants


# ---------------------------------------------------------------------------
# The checks, one per claim of task 10.2
# ---------------------------------------------------------------------------


def assert_every_request_succeeded(participants: list[Participant]) -> None:
    """*Forty spaces at once*: no request is answered with an error."""
    crashed = [
        (participant.space, repr(participant.failure))
        for participant in participants
        if participant.failure is not None
    ]
    assert crashed == []

    failures = [
        (participant.space, path, code, body[:200])
        for participant in participants
        for (path, code), body in zip(participant.statuses, participant.bodies)
        if not 200 <= code < 300
    ]
    assert failures == []
    assert [len(participant.statuses) for participant in participants] == [
        REQUESTS_PER_PARTICIPANT
    ] * PARTICIPANTS


def assert_nothing_was_locked_out(participants: list[Participant], locked: list[str]) -> None:
    """A writer collision is a short wait, never ``database is locked``."""
    assert locked == []

    leaked = [
        (participant.space, body[:200])
        for participant in participants
        for body in participant.bodies
        if LOCKED_MESSAGE in body.lower()
    ]
    assert leaked == []

    crashes = [
        (participant.space, str(participant.failure))
        for participant in participants
        if participant.failure is not None
        and LOCKED_MESSAGE in str(participant.failure).lower()
    ]
    assert crashes == []


def assert_each_space_sees_its_own_status(participants: list[Participant]) -> None:
    """The status of a space reports that space and the preset it applied."""
    reported = {
        participant.space: (
            participant.status.get("space"),
            participant.status.get("locator_stage"),
        )
        for participant in participants
    }
    expected = {
        participant.space: (participant.space, participant.expected_stage)
        for participant in participants
    }

    assert reported == expected


def assert_each_space_sees_its_own_cart(participants: list[Participant]) -> None:
    """The cart of a space holds the item that space added, and nothing else."""
    reported = {
        participant.space: (
            [(item["product_id"], item["quantity"]) for item in participant.cart.get("items", [])],
            participant.cart.get("session"),
        )
        for participant in participants
    }
    expected = {
        # The reported session id never carries the space prefix (design D3).
        participant.space: ([(participant.product_id, participant.quantity)], participant.session_id)
        for participant in participants
    }

    assert reported == expected


def assert_rows_are_partitioned_by_space(participants: list[Participant]) -> None:
    """The rows on disk are partitioned by space, one set per participant."""
    cart_keys = {row[0] for row in sqlite_rows("SELECT session_key FROM cart_items")}
    assert cart_keys == {f"{p.space}:{p.session_id}" for p in participants}

    orders = dict(sqlite_rows("SELECT order_number, space FROM orders"))
    assert orders == {p.order_number: p.space for p in participants}

    flag_spaces = {row[0] for row in sqlite_rows("SELECT DISTINCT space FROM space_feature_flags")}
    assert flag_spaces == {p.space for p in participants}


def test_forty_spaces_shop_concurrently(temp_database: Path, fake_weasyprint) -> None:
    """*Concurrent workshop*: forty spaces, one database, no interference."""
    watcher = LockWatcher()
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(watcher)
    # Low enough for anything the application or its libraries report about a
    # lock, high enough to leave out the per-statement DEBUG noise of aiosqlite.
    root.setLevel(logging.INFO)
    try:
        participants = asyncio.run(run_workshop())
    finally:
        root.removeHandler(watcher)
        root.setLevel(previous_level)

    assert_every_request_succeeded(participants)
    assert_nothing_was_locked_out(participants, watcher.locked)
    assert_each_space_sees_its_own_status(participants)
    assert_each_space_sees_its_own_cart(participants)
    assert_rows_are_partitioned_by_space(participants)
