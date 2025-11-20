from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from sqlalchemy import select, text, delete

from ..core.db import get_session_factory, init_db
from ..models.feature_flag import FeatureFlag
from ..models.order import Order
from ..models.product import Product
from ..models.user import Address, PaymentMethod, User
from ..services.order_service import CustomerDetails, OrderService
from ..services.pdf_service import PDFService
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

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


async def ensure_product_columns(session) -> None:
    result = await session.execute(text("PRAGMA table_info(products)"))
    columns = {row[1] for row in result.fetchall()}
    if "rating" not in columns:
        await session.execute(text("ALTER TABLE products ADD COLUMN rating FLOAT"))
    if "review_count" not in columns:
        await session.execute(text("ALTER TABLE products ADD COLUMN review_count INTEGER DEFAULT 0"))
    await session.commit()


async def ensure_order_columns(session) -> None:
    result = await session.execute(text("PRAGMA table_info(orders)"))
    columns = {row[1] for row in result.fetchall()}
    alterations = []
    if "user_id" not in columns:
        alterations.append("ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    if "shipping_address_id" not in columns:
        alterations.append("ADD COLUMN shipping_address_id INTEGER REFERENCES addresses(id) ON DELETE SET NULL")
    if "billing_address_id" not in columns:
        alterations.append("ADD COLUMN billing_address_id INTEGER REFERENCES addresses(id) ON DELETE SET NULL")
    if "payment_method_id" not in columns:
        alterations.append("ADD COLUMN payment_method_id INTEGER REFERENCES payment_methods(id) ON DELETE SET NULL")
    for clause in alterations:
        await session.execute(text(f"ALTER TABLE orders {clause}"))
    if alterations:
        await session.commit()


async def seed_products(session) -> None:
    await ensure_product_columns(session)
    for product in PRODUCT_FIXTURES:
        existing = await session.scalar(select(Product).where(Product.sku == product["sku"]))
        if existing:
            for field, value in product.items():
                setattr(existing, field, value)
        else:
            session.add(Product(**product))

    await session.commit()
    logger.info("Seeded %d products", len(PRODUCT_FIXTURES))


async def seed_feature_flags(session) -> None:
    existing = await session.scalars(select(FeatureFlag))
    existing_keys = {flag.key for flag in existing}

    for flag in FEATURE_FLAGS:
        if flag["key"] not in existing_keys:
            session.add(FeatureFlag(**flag))

    await session.commit()
    logger.info("Ensured feature flags: %s", ", ".join(flag["key"] for flag in FEATURE_FLAGS))


async def seed_users(session) -> None:
    await ensure_order_columns(session)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    pdf_service = PDFService(env)
    order_service = OrderService(session, pdf_service)

    products = await session.execute(select(Product))
    product_by_sku = {product.sku: product for product in products.scalars().all()}

    for user_data in USERS_FIXTURES:
        existing_user = await session.scalar(select(User).where(User.email == user_data["email"]))
        password_hash = hashlib.sha256(user_data["password"].encode()).hexdigest()
        if existing_user:
            existing_user.full_name = user_data["full_name"]
            existing_user.password_hash = password_hash
            user = existing_user
            await session.execute(delete(Address).where(Address.user_id == user.id))
            await session.execute(delete(PaymentMethod).where(PaymentMethod.user_id == user.id))
            await session.execute(delete(Order).where(Order.user_id == user.id))
            await session.flush()
        else:
            user = User(email=user_data["email"], full_name=user_data["full_name"], password_hash=password_hash)
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
            billing_idx = payment_data.pop("billing_address_index", None)
            billing_address_id = addresses[billing_idx].id if billing_idx is not None and addresses else None
            payment = PaymentMethod(
                user_id=user.id,
                billing_address_id=billing_address_id,
                **payment_data,
            )
            session.add(payment)
            payments.append(payment)
        await session.flush()

        for order_data in user_data.get("orders", []):
            shipping_idx = order_data.get("shipping_address_index")
            billing_idx = order_data.get("billing_address_index")
            payment_idx = order_data.get("payment_method_index")

            shipping_address = addresses[shipping_idx] if shipping_idx is not None and len(addresses) > shipping_idx else None
            billing_address = addresses[billing_idx] if billing_idx is not None and len(addresses) > billing_idx else None
            payment_method = payments[payment_idx] if payment_idx is not None and len(payments) > payment_idx else None

            cart_items = []
            for item in order_data.get("items", []):
                product = product_by_sku.get(item["sku"])
                if not product:
                    logger.warning("Skipping unknown product SKU %s for user %s", item["sku"], user.email)
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

            if not cart_items:
                continue

            cart_state = {"items": cart_items}
            address_source = shipping_address or billing_address or (addresses[0] if addresses else None)
            formatted_address = (
                f"{address_source.line1}, {address_source.city}, {address_source.state} {address_source.postal_code}"
                if address_source
                else "Unknown"
            )

            customer = CustomerDetails(
                name=user.full_name,
                email=user.email,
                address=formatted_address,
            )
            order, _ = await order_service.create_order(
                customer,
                cart_state,
                user_id=user.id,
                shipping_address_id=shipping_address.id if shipping_address else None,
                billing_address_id=billing_address.id if billing_address else None,
                payment_method_id=payment_method.id if payment_method else None,
            )
            order.status = order_data.get("status", "processing")
            session.add(order)

    await session.commit()
    logger.info("Seeded demo users with history: %s", ", ".join(user["email"] for user in USERS_FIXTURES))


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
