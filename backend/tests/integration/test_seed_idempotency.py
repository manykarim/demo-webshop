"""Seeding is safe to run on every start (tasks 4.1 and 4.2, design D4).

Every check runs ``seed_data.main()`` against a real SQLite file and reads the
result back with stdlib ``sqlite3``, outside SQLAlchemy, so an identity map or a
cached object cannot make a non-idempotent seed look idempotent.
"""
from __future__ import annotations

import asyncio
import copy
import re
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

import pytest

from backend.app.core.config import settings
from backend.app.seeds import seed_data
from backend.tests.harness import isolated_database

JAMIE = "jamie@flowlinesupply.com"
ALEX = "alex.productlead@example.com"

#: The billing links the fixtures describe, as ``(email, brand, last4, address label)``.
EXPECTED_BILLING_LINKS = [
    (JAMIE, "Visa", "4242", "Home"),
    (JAMIE, "Amex", "3782", "Studio"),
    (ALEX, "Mastercard", "5454", "Primary"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_seed() -> None:
    """Run ``seed_data.main()`` and dispose the engine, in one event loop.

    The engine belongs to the loop that created it, so every run needs its own
    loop *and* its own engine - exactly what ``tools/entrypoint.py`` does.
    """

    async def runner() -> None:
        from backend.app.core.db import shutdown_db

        try:
            await seed_data.main()
        finally:
            await shutdown_db()

    asyncio.run(runner())


def rows(database_path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    with closing(sqlite3.connect(database_path)) as connection:
        return connection.execute(sql, params).fetchall()


def scalar(database_path: Path, sql: str, params: tuple = ()):
    return rows(database_path, sql, params)[0][0]


def execute(database_path: Path, sql: str, params: tuple = ()) -> None:
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute(sql, params)
        connection.commit()


def counts(database_path: Path) -> dict[str, int]:
    """Row counts of every table seeding writes to."""
    return {
        table: scalar(database_path, f"SELECT COUNT(*) FROM {table}")
        for table in ("users", "addresses", "payment_methods", "orders", "order_items")
    }


def order_numbers(database_path: Path, email: str | None = None) -> list[str]:
    """Seeded order numbers, ordered by id. ``email`` narrows to one user."""
    if email is None:
        return [
            row[0]
            for row in rows(
                database_path,
                "SELECT order_number FROM orders WHERE user_id IS NOT NULL ORDER BY id",
            )
        ]
    return [
        row[0]
        for row in rows(
            database_path,
            "SELECT o.order_number FROM orders o JOIN users u ON u.id = o.user_id"
            " WHERE u.email = ? ORDER BY o.id",
            (email,),
        )
    ]


def emails(database_path: Path) -> list[str]:
    return [row[0] for row in rows(database_path, "SELECT email FROM users ORDER BY id")]


def billing_links(database_path: Path) -> list[tuple]:
    """``(email, brand, last4, billing address label)`` for every payment method."""
    return rows(
        database_path,
        "SELECT u.email, pm.brand, pm.last4, a.label"
        " FROM payment_methods pm"
        " JOIN users u ON u.id = pm.user_id"
        " LEFT JOIN addresses a ON a.id = pm.billing_address_id"
        " ORDER BY u.id, pm.id",
    )


def assert_billing_links_match_the_fixtures(database_path: Path) -> None:
    """Every payment method points at the address the fixture's index names.

    Checked twice over: against the labels spelled out in the change (a
    regression that renumbered the links would still satisfy a self-referential
    check) and against ``USERS_FIXTURES`` itself, addresses ordered by id.
    """
    assert billing_links(database_path) == EXPECTED_BILLING_LINKS

    for user in seed_data.USERS_FIXTURES:
        address_ids = [
            row[0]
            for row in rows(
                database_path,
                "SELECT a.id FROM addresses a JOIN users u ON u.id = a.user_id"
                " WHERE u.email = ? ORDER BY a.id",
                (user["email"],),
            )
        ]
        persisted = rows(
            database_path,
            "SELECT pm.billing_address_id FROM payment_methods pm JOIN users u ON u.id = pm.user_id"
            " WHERE u.email = ? ORDER BY pm.id",
            (user["email"],),
        )
        assert len(persisted) == len(user["payment_methods"])
        for (billing_address_id,), fixture in zip(persisted, user["payment_methods"]):
            assert billing_address_id is not None
            assert billing_address_id == address_ids[fixture["billing_address_index"]]


@contextmanager
def build_order_failing_for(email: str):
    """Make ``build_order`` raise for one fixture user, as a crash mid-seed would."""
    original = seed_data.build_order

    def guarded(customer, cart_state, **kwargs):
        if customer.email == email:
            raise RuntimeError("simulated seed failure")
        return original(customer, cart_state, **kwargs)

    seed_data.build_order = guarded
    try:
        yield
    finally:
        seed_data.build_order = original


def pdf_output_dir() -> Path:
    return Path(settings.pdf_output_dir)


# ---------------------------------------------------------------------------
# Task 4.1 - products, feature flags and the column helpers
# ---------------------------------------------------------------------------


def test_a_fresh_database_gets_every_product(temp_database):
    run_seed()

    assert scalar(temp_database, "SELECT COUNT(*) FROM products") == 12
    assert len(seed_data.PRODUCT_FIXTURES) == 12
    assert scalar(temp_database, "SELECT COUNT(*) FROM feature_flags") == len(seed_data.FEATURE_FLAGS)


def test_a_second_run_never_overwrites_products_or_flags(temp_database):
    run_seed()

    sku = seed_data.PRODUCT_FIXTURES[0]["sku"]
    flag_key = seed_data.FEATURE_FLAGS[0]["key"]
    assert seed_data.FEATURE_FLAGS[0]["enabled"] is False
    execute(temp_database, "UPDATE products SET price = 1.23 WHERE sku = ?", (sku,))
    execute(temp_database, "UPDATE feature_flags SET enabled = 1 WHERE key = ?", (flag_key,))

    run_seed()

    assert scalar(temp_database, "SELECT price FROM products WHERE sku = ?", (sku,)) == 1.23
    assert scalar(temp_database, "SELECT enabled FROM feature_flags WHERE key = ?", (flag_key,)) == 1
    assert scalar(temp_database, "SELECT COUNT(*) FROM products") == 12


def test_missing_product_columns_are_added_to_a_raw_database(temp_database):
    """A ``products`` table from older DDL gains ``rating`` and ``review_count``."""
    execute(
        temp_database,
        """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name VARCHAR(120) NOT NULL,
            sku VARCHAR(64) NOT NULL UNIQUE,
            price FLOAT NOT NULL,
            description TEXT NOT NULL,
            image_url VARCHAR(255),
            category VARCHAR(64),
            inventory INTEGER NOT NULL DEFAULT 0
        )
        """,
    )
    columns_before = {row[1] for row in rows(temp_database, "PRAGMA table_info(products)")}
    assert "rating" not in columns_before and "review_count" not in columns_before

    run_seed()

    columns_after = {row[1] for row in rows(temp_database, "PRAGMA table_info(products)")}
    assert "rating" in columns_after
    assert "review_count" in columns_after
    assert scalar(temp_database, "SELECT COUNT(*) FROM products") == 12


# ---------------------------------------------------------------------------
# Task 4.2 - users, their history and repeated runs
# ---------------------------------------------------------------------------


def test_two_runs_leave_the_seeded_data_and_a_runtime_order_untouched(temp_database):
    run_seed()

    execute(
        temp_database,
        "INSERT INTO orders (order_number, user_id, customer_name, customer_email,"
        " customer_address, subtotal, tax, total, status, created_at)"
        " VALUES ('ORD-RUNTIME', NULL, 'Walk In', 'walkin@example.com', 'Somewhere',"
        " 10.0, 0.7, 10.7, 'processing', '2026-01-01 00:00:00')",
    )
    before = counts(temp_database)
    seeded_numbers_before = order_numbers(temp_database)
    assert emails(temp_database) == [JAMIE, ALEX]
    assert len(seeded_numbers_before) == 3

    run_seed()

    assert counts(temp_database) == before
    assert order_numbers(temp_database) == seeded_numbers_before
    assert scalar(temp_database, "SELECT COUNT(*) FROM orders WHERE order_number = 'ORD-RUNTIME'") == 1
    orphans = scalar(
        temp_database,
        "SELECT COUNT(*) FROM order_items oi LEFT JOIN orders o ON o.id = oi.order_id WHERE o.id IS NULL",
    )
    assert orphans == 0
    assert list(pdf_output_dir().iterdir()) == []


def test_seeded_orders_carry_their_fixture_status(temp_database):
    run_seed()

    statuses = rows(
        temp_database,
        "SELECT u.email, o.status FROM orders o JOIN users u ON u.id = o.user_id ORDER BY o.id",
    )
    expected = [
        (user["email"], order["status"])
        for user in seed_data.USERS_FIXTURES
        for order in user["orders"]
    ]
    assert statuses == expected


def test_seed_data_builds_no_order_service_and_no_renderer():
    """The grep of task 4.2, as a test that travels with the suite."""
    source = Path(seed_data.__file__).read_text(encoding="utf-8")
    assert re.search(r"PDFService|OrderService", source) is None


def test_a_failed_user_seed_leaves_no_partial_user_and_a_retry_completes_it(temp_database):
    with build_order_failing_for(ALEX), pytest.raises(RuntimeError, match="simulated seed failure"):
        run_seed()

    # The first user is complete, the second left no trace at all.
    assert emails(temp_database) == [JAMIE]
    jamie_numbers = order_numbers(temp_database, JAMIE)
    assert len(jamie_numbers) == 2
    assert counts(temp_database) == {
        "users": 1,
        "addresses": 2,
        "payment_methods": 2,
        "orders": 2,
        "order_items": 4,
    }

    run_seed()

    assert emails(temp_database) == [JAMIE, ALEX]
    assert order_numbers(temp_database, JAMIE) == jamie_numbers
    assert len(order_numbers(temp_database, ALEX)) == 1
    assert list(pdf_output_dir().iterdir()) == []


def test_billing_links_survive_a_failed_seed_and_its_retry(temp_database):
    with build_order_failing_for(ALEX), pytest.raises(RuntimeError, match="simulated seed failure"):
        run_seed()

    run_seed()

    assert_billing_links_match_the_fixtures(temp_database)


def test_billing_links_are_right_after_an_earlier_in_process_seed(tmp_path):
    """Two fresh databases seeded one after the other in the same process.

    A seed that consumed its fixtures (``pop``) produced correct links only for
    the first database of a process, so test order alone could hide the defect.
    """
    for name in ("first", "second"):
        with isolated_database(tmp_path / name) as database_path:
            run_seed()
            assert_billing_links_match_the_fixtures(database_path)


def test_fixtures_are_never_mutated(tmp_path):
    snapshot = copy.deepcopy(seed_data.USERS_FIXTURES)

    with isolated_database(tmp_path / "twice"):
        run_seed()
        run_seed()
    assert seed_data.USERS_FIXTURES == snapshot

    with isolated_database(tmp_path / "retry"):
        with build_order_failing_for(ALEX), pytest.raises(RuntimeError, match="simulated seed failure"):
            run_seed()
        run_seed()
    assert seed_data.USERS_FIXTURES == snapshot


def test_seeded_documents_are_rendered_on_first_request(seeded_app_client, fake_weasyprint):
    """Seeding writes no PDF; the document endpoints render on demand (design D4/D8)."""
    assert list(pdf_output_dir().iterdir()) == []

    response = seeded_app_client.post(
        "/api/auth/login",
        json={"email": JAMIE, "password": "demo123"},
    )

    assert response.status_code == 200, response.text
    orders = response.json()["orders"]
    assert len(orders) == 2
    assert fake_weasyprint == []
    assert list(pdf_output_dir().iterdir()) == []

    for order in orders:
        for url in (order["invoice_url"], order["summary_url"]):
            document = seeded_app_client.get(url)

            assert document.status_code == 200, document.text
            assert document.headers["content-type"] == "application/pdf"
            assert document.content.startswith(b"%PDF")

    assert len(fake_weasyprint) == 4
