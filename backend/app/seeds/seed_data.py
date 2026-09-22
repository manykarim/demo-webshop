"""Insert-if-missing demo data, safe to run on every container start (design D4).

``main()`` is idempotent: it adds what is missing and never updates or deletes an
existing row, so a restart on a persisted database keeps runtime changes (edited
prices, toggled feature flags, orders placed by participants), while a newer
image still gains new fixtures.

Two rules make repeated runs identical:

* The fixture lists below are **read-only**. Indexes such as
  ``billing_address_index`` are read with ``.get`` and model arguments are built
  from a filtered copy - never through ``pop``, ``del`` or item assignment. A
  second in-process run (a test, a harness fixture, a retry after a failed seed)
  therefore sees exactly the same fixture data as the first.
* Each new user is written as one unit: the user, the addresses, the payment
  methods and the seeded order history are committed together, once per user, so
  a crash can never leave a half-seeded user that a later start would skip.

Seeding renders no PDF and constructs neither an order service - whose
constructor would require a renderer - nor a renderer. Orders are built with the
module-level ``build_order`` helper (design D8); their documents are rendered on
first request by ``api/docs.py``.

Consequence for development: this no longer refreshes an existing database. To
reset, delete the SQLite file.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging

from sqlalchemy import select

from ..core.db import (  # noqa: F401  # re-exported: importable from here as before
    ensure_order_columns,
    ensure_product_columns,
    get_session_factory,
    init_db,
)
from ..core.workshop import PLANTED_BUGS
from ..models.feature_flag import FeatureFlag
from ..models.product import Product
from ..models.user import Address, PaymentMethod, User
from ..services.order_service import CustomerDetails, build_order

logger = logging.getLogger(__name__)

PRODUCT_FIXTURES = [
    {
        "name": "Aurora Neural Headphones",
        "sku": "AUR-NEU-001",
        "price": 249.99,
        "description": "Spatial audio headphones with adaptive noise control, AI-powered equaliser presets, and all-day comfort for deep work sessions.",
        "image_url": "/static/img/aurora-headphones.jpg",
        "category": "Audio",
        "inventory": 25,
        "rating": 4.8,
        "review_count": 214,
    },
    {
        "name": "Insight Smart Notebook",
        "sku": "INS-NOT-002",
        "price": 39.5,
        "description": "Reusable smart notebook that digitises handwritten notes, highlights key ideas automatically, and syncs to your second brain.",
        "image_url": "/static/img/insight-notebook.jpg",
        "category": "Productivity",
        "inventory": 120,
        "rating": 4.6,
        "review_count": 168,
    },
    {
        "name": "Pulse Bio Ring",
        "sku": "PUL-RNG-003",
        "price": 189.0,
        "description": "Titanium wellness ring measuring biometrics with personalised recovery insights, sleep coaching, and training recommendations.",
        "image_url": "/static/img/pulse-ring.jpg",
        "category": "Health",
        "inventory": 60,
        "rating": 4.7,
        "review_count": 321,
    },
    {
        "name": "Nimbus Desk Light",
        "sku": "NIM-LGT-004",
        "price": 129.0,
        "description": "Daylight-balancing desk light that adapts colour temperature to your circadian rhythm, calendar, and focus sessions.",
        "image_url": "/static/img/nimbus-light.jpg",
        "category": "Home Office",
        "inventory": 45,
        "rating": 4.5,
        "review_count": 142,
    },
    {
        "name": "Atlas Standing Desk",
        "sku": "ATL-DSK-005",
        "price": 799.0,
        "description": "Programmable standing desk with posture coaching, ambient wellness reminders, and built-in cable management.",
        "image_url": "/static/img/atlas-desk.jpg",
        "category": "Furniture",
        "inventory": 15,
        "rating": 4.9,
        "review_count": 98,
    },
    {
        "name": "Velocity Travel Backpack",
        "sku": "VEL-BPK-006",
        "price": 169.0,
        "description": "Weatherproof travel backpack with modular compartments, RFID shielded pocket, and integrated power routing for devices.",
        "image_url": "/static/img/velocity-backpack.jpg",
        "category": "Travel",
        "inventory": 110,
        "rating": 4.4,
        "review_count": 205,
    },
    {
        "name": "Horizon Portable Display",
        "sku": "HOR-DSP-007",
        "price": 389.0,
        "description": "4K OLED portable display with auto-rotate, dual USB-C, and colour-accurate quantum-dot panel for remote creators.",
        "image_url": "/static/img/horizon-display.jpg",
        "category": "Displays",
        "inventory": 32,
        "rating": 4.6,
        "review_count": 187,
    },
    {
        "name": "Focus Loop Timer",
        "sku": "FCS-TMR-008",
        "price": 59.0,
        "description": "Physical pomodoro timer that syncs with calendars, nudges mindful breaks, and tracks context switching costs.",
        "image_url": "/static/img/focus-loop.jpg",
        "category": "Productivity",
        "inventory": 210,
        "rating": 4.5,
        "review_count": 264,
    },
    {
        "name": "Summit Trail Shoes",
        "sku": "SUM-SHO-009",
        "price": 149.0,
        "description": "Trail shoes with adaptive grip pattern, live weather alerts, and AI coaching for pacing, hydration, and recovery.",
        "image_url": "/static/img/summit-shoes.jpg",
        "category": "Outdoors",
        "inventory": 65,
        "rating": 4.3,
        "review_count": 156,
    },
    {
        "name": "Echo Conference Speaker",
        "sku": "ECH-SPK-010",
        "price": 219.0,
        "description": "360° conference speaker with beamforming microphones, live transcription, and collaborative note handoff.",
        "image_url": "/static/img/echo-speaker.jpg",
        "category": "Audio",
        "inventory": 80,
        "rating": 4.7,
        "review_count": 112,
    },
    {
        "name": "Orbit Drone Camera",
        "sku": "ORB-DRN-011",
        "price": 899.0,
        "description": "Compact drone with autonomous flight plans, cinematic presets, and multi-sensor collision avoidance.",
        "image_url": "/static/img/orbit-drone.jpg",
        "category": "Imaging",
        "inventory": 22,
        "rating": 4.4,
        "review_count": 91,
    },
    {
        "name": "Cascade Water Bottle",
        "sku": "CAS-BOT-012",
        "price": 79.0,
        "description": "Smart hydration bottle that tracks intake, delivers pacing reminders, and purifies water on-demand.",
        "image_url": "/static/img/cascade-bottle.jpg",
        "category": "Health",
        "inventory": 140,
        "rating": 4.2,
        "review_count": 134,
    },
]

FEATURE_FLAGS = [
    {"key": "NEW_CART_UI", "description": "Enable redesigned cart experience", "enabled": False},
    {"key": "MOBILE_UI_V1", "description": "Apply mobile-first responsive tweaks", "enabled": False},
    {"key": "SEARCH_V2", "description": "Use semantic search beta", "enabled": False},
    # Workshop: Locator Variations (for self-healing testing)
    {"key": "LOCATOR_V2", "description": "Stage 2: Change element IDs and classes", "enabled": False},
    {"key": "LOCATOR_V3", "description": "Stage 3: Remove data-test attributes", "enabled": False},
    {"key": "LOCATOR_V4", "description": "Stage 4: Restructure DOM hierarchy", "enabled": False},
    # Workshop: Intentional Bugs. Generated from the registry in
    # ``core/workshop.py`` (design Decision 9), so a new planted bug gets its
    # seeded row - disabled, like every other bug - without a second edit here.
    *(
        {"key": bug.flag, "description": bug.seed_description, "enabled": False}
        for bug in PLANTED_BUGS
    ),
    # Workshop: AI Response Variations
    {"key": "AI_DETERMINISTIC", "description": "AI: Force deterministic mock responses", "enabled": True},
    {"key": "AI_RANDOM_DELAYS", "description": "AI: Add random response delays", "enabled": False},
    {"key": "AI_VARIED_RESPONSES", "description": "AI: Enable response variation", "enabled": False},
]

USERS_FIXTURES = [
    {
        "email": "jamie@flowlinesupply.com",
        "password": "demo123",
        "full_name": "Jamie Rivera",
        "addresses": [
            {
                "label": "Home",
                "line1": "123 Flow Street",
                "line2": "Suite 400",
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94107",
                "country": "USA",
            },
            {
                "label": "Studio",
                "line1": "88 Market Lane",
                "line2": None,
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94105",
                "country": "USA",
            },
        ],
        "payment_methods": [
            {"brand": "Visa", "last4": "4242", "exp_month": 7, "exp_year": 2027, "billing_address_index": 0},
            {"brand": "Amex", "last4": "3782", "exp_month": 11, "exp_year": 2026, "billing_address_index": 1},
        ],
        "orders": [
            {
                "items": [
                    {"sku": "AUR-NEU-001", "quantity": 1},
                    {"sku": "INS-NOT-002", "quantity": 2},
                ],
                "shipping_address_index": 0,
                "billing_address_index": 0,
                "payment_method_index": 0,
                "status": "fulfilled",
            },
            {
                "items": [
                    {"sku": "ATL-DSK-005", "quantity": 1},
                    {"sku": "NIM-LGT-004", "quantity": 1},
                ],
                "shipping_address_index": 1,
                "billing_address_index": 1,
                "payment_method_index": 1,
                "status": "processing",
            },
        ],
    },
    {
        "email": "alex.productlead@example.com",
        "password": "flowline",
        "full_name": "Alex Morgan",
        "addresses": [
            {
                "label": "Primary",
                "line1": "22 Gradient Ave",
                "line2": "Apt 12B",
                "city": "New York",
                "state": "NY",
                "postal_code": "10010",
                "country": "USA",
            }
        ],
        "payment_methods": [
            {"brand": "Mastercard", "last4": "5454", "exp_month": 4, "exp_year": 2028, "billing_address_index": 0}
        ],
        "orders": [
            {
                "items": [
                    {"sku": "HOR-DSP-007", "quantity": 1},
                    {"sku": "VEL-BPK-006", "quantity": 1},
                    {"sku": "CAS-BOT-012", "quantity": 2},
                ],
                "shipping_address_index": 0,
                "billing_address_index": 0,
                "payment_method_index": 0,
                "status": "fulfilled",
            }
        ],
    },
]


async def seed_products(session) -> None:
    """Insert missing SKUs; never update an existing product row (design D4).

    A price, an inventory level or a description edited at runtime survives every
    later start, and a newer image still adds SKUs the database does not know.
    The schema helpers run in ``init_db()`` (design D3), which every caller of
    this function has already awaited.
    """
    existing_skus = set((await session.scalars(select(Product.sku))).all())

    inserted = 0
    for product in PRODUCT_FIXTURES:
        if product["sku"] in existing_skus:
            continue
        session.add(Product(**product))
        inserted += 1

    await session.commit()
    logger.info("Ensured %d products (%d inserted)", len(PRODUCT_FIXTURES), inserted)


async def seed_feature_flags(session) -> None:
    existing = await session.scalars(select(FeatureFlag))
    existing_keys = {flag.key for flag in existing}

    for flag in FEATURE_FLAGS:
        if flag["key"] not in existing_keys:
            session.add(FeatureFlag(**flag))

    await session.commit()
    logger.info("Ensured feature flags: %s", ", ".join(flag["key"] for flag in FEATURE_FLAGS))


def _build_cart_items(order_data: dict, product_by_sku: dict, email: str) -> list[dict]:
    """The cart state of one fixture order, read-only on ``order_data``."""
    cart_items: list[dict] = []
    for item in order_data.get("items", []):
        product = product_by_sku.get(item["sku"])
        if not product:
            logger.warning("Skipping unknown product SKU %s for user %s", item["sku"], email)
            continue
        quantity = item.get("quantity", 1)
        cart_items.append(
            {
                "product_id": product.id,
                "name": product.name,
                "quantity": quantity,
                "unit_price": product.price,
                "total_price": round(product.price * quantity, 2),
            }
        )
    return cart_items


def _pick(items: list, index: int | None):
    """``items[index]`` when the fixture index addresses an existing entry."""
    if index is None or not 0 <= index < len(items):
        return None
    return items[index]


async def _seed_user(session, user_data: dict, product_by_sku: dict) -> None:
    """Create one new user with addresses, payment methods and order history.

    Everything is written with ``session.add`` and committed once, at the end, so
    an exception anywhere in between leaves no trace of this user: the enclosing
    session is closed by ``main()`` and the flushed rows are rolled back.
    """
    user = User(
        email=user_data["email"],
        full_name=user_data["full_name"],
        password_hash=hashlib.sha256(user_data["password"].encode()).hexdigest(),
    )
    session.add(user)
    await session.flush()

    addresses: list[Address] = []
    for address_data in user_data.get("addresses", []):
        address = Address(user_id=user.id, **address_data)
        session.add(address)
        addresses.append(address)
    await session.flush()

    payments: list[PaymentMethod] = []
    for payment_data in user_data.get("payment_methods", []):
        # Read-only on the fixture: the index is read with ``.get`` and the model
        # arguments come from a filtered copy. Combining ``.get`` with
        # ``**payment_data`` would hand ``billing_address_index`` to
        # ``PaymentMethod`` and raise ``TypeError``; ``pop`` would destroy the
        # fixture for every later run in this process.
        billing_address = _pick(addresses, payment_data.get("billing_address_index"))
        payment = PaymentMethod(
            user_id=user.id,
            billing_address_id=billing_address.id if billing_address else None,
            **{key: value for key, value in payment_data.items() if key != "billing_address_index"},
        )
        session.add(payment)
        payments.append(payment)
    await session.flush()

    for order_data in user_data.get("orders", []):
        cart_items = _build_cart_items(order_data, product_by_sku, user.email)
        if not cart_items:
            continue

        shipping_address = _pick(addresses, order_data.get("shipping_address_index"))
        billing_address = _pick(addresses, order_data.get("billing_address_index"))
        payment_method = _pick(payments, order_data.get("payment_method_index"))

        address_source = shipping_address or billing_address or (addresses[0] if addresses else None)
        formatted_address = (
            f"{address_source.line1}, {address_source.city}, {address_source.state} {address_source.postal_code}"
            if address_source
            else "Unknown"
        )

        # ``build_order`` needs no session and no renderer (design D8), so
        # seeding neither commits half an order nor writes a PDF.
        order = build_order(
            CustomerDetails(name=user.full_name, email=user.email, address=formatted_address),
            {"items": cart_items},
            user_id=user.id,
            shipping_address_id=shipping_address.id if shipping_address else None,
            billing_address_id=billing_address.id if billing_address else None,
            payment_method_id=payment_method.id if payment_method else None,
            status=order_data.get("status", "processing"),
        )
        session.add(order)

    await session.commit()


async def seed_users(session) -> None:
    """Insert missing demo users, one commit per user (design D4).

    A user whose email already exists is left completely alone - name, password,
    addresses, payment methods and orders included - so runtime changes and
    participant orders survive a restart.

    The schema helpers run in ``init_db()`` (design D3), which every caller of
    this function has already awaited.
    """
    products = await session.execute(select(Product))
    product_by_sku = {product.sku: product for product in products.scalars().all()}

    inserted: list[str] = []
    for user_data in USERS_FIXTURES:
        existing_user = await session.scalar(select(User.id).where(User.email == user_data["email"]))
        if existing_user is not None:
            continue
        await _seed_user(session, user_data, product_by_sku)
        inserted.append(user_data["email"])

    logger.info(
        "Ensured %d demo users with history (%s)",
        len(USERS_FIXTURES),
        ", ".join(inserted) if inserted else "none inserted",
    )


async def main() -> None:
    await init_db()
    session_factory = get_session_factory()
    async with session_factory() as session:
        await seed_products(session)
        await seed_feature_flags(session)
        await seed_users(session)
    logger.info("Seeding completed")


if __name__ == "__main__":
    asyncio.run(main())
