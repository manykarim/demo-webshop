from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from .core.config import settings
from .core.db import get_session, init_db, shutdown_db
from .core.feature_flags import list_feature_flags
from .core.templatetags import format_currency
from .services.cart_service import CartService
from .services.product_service import ProductService
from .services.order_service import CustomerDetails, OrderService
from .services.pdf_service import PDFService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise and tear down shared resources."""
    await init_db()
    try:
        yield
    finally:
        await shutdown_db()


app = FastAPI(
    title="AI Testing Workshop",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=settings.docs_url,
    redoc_url=settings.redoc_url,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _mount_static_and_templates(application: FastAPI) -> None:
    static_dir = Path(__file__).parent / "static"
    templates_dir = Path(__file__).parent / "templates"

    if static_dir.exists():
        application.mount("/static", StaticFiles(directory=static_dir), name="static")

    if templates_dir.exists():
        templates = Jinja2Templates(directory=str(templates_dir))
    else:
        templates = Jinja2Templates(directory=str(templates_dir))

    templates.env.filters["currency"] = format_currency
    templates.env.globals["brand_name"] = "Flowline Supply"
    app.state.templates = templates


_mount_static_and_templates(app)


def get_templates() -> Jinja2Templates:
    return app.state.templates


def resolve_session_key(request: Request) -> str:
    header_session_id = request.headers.get("x-session-id")
    cookie_session_id = request.cookies.get("session_id")
    return header_session_id or cookie_session_id or "workshop-demo"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home_page(request: Request, session: AsyncSession = Depends(get_session)):
    templates = get_templates()
    product_service = ProductService(session)
    newest_products = await product_service.list_products(order="newest")
    featured_products = newest_products[:4]
    popular_products = sorted(newest_products, key=lambda item: item["inventory"], reverse=True)[:4]
    premium_picks = sorted(newest_products, key=lambda item: item["price"], reverse=True)[:4]
    categories = await product_service.list_categories()
    flags = await list_feature_flags(session)
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "featured_products": featured_products,
            "popular_products": popular_products,
            "premium_picks": premium_picks,
            "newest_products": newest_products[:8],
            "categories": categories,
            "feature_flags": flags,
        },
    )


@app.get("/products", response_class=HTMLResponse, include_in_schema=False)
async def products_page(request: Request, session: AsyncSession = Depends(get_session)):
    templates = get_templates()
    product_service = ProductService(session)
    query_params = request.query_params
    selected_categories = query_params.getlist("category")
    if not selected_categories:
        single_category = query_params.get("category")
        if single_category:
            selected_categories = [single_category]
    normalized_categories = [value.lower() for value in selected_categories if value]

    def parse_float(value: str | None) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except ValueError:
            return None

    price_min_param = parse_float(query_params.get("price_min"))
    price_max_param = parse_float(query_params.get("price_max"))
    rating_param = parse_float(query_params.get("rating"))
    availability_param = query_params.get("availability")
    in_stock = availability_param == "in_stock"

    price_bounds = await product_service.get_price_bounds()

    if price_min_param is not None and price_max_param is not None and price_min_param > price_max_param:
        price_min_param, price_max_param = price_max_param, price_min_param

    price_min = price_min_param if price_min_param is not None else price_bounds[0]
    price_max = price_max_param if price_max_param is not None else price_bounds[1]

    products = await product_service.list_products(
        order="name",
        categories=normalized_categories if normalized_categories else None,
        price_min=price_min_param,
        price_max=price_max_param,
        rating_min=rating_param,
        in_stock=in_stock,
    )

    categories = await product_service.list_categories()
    highlighted = await product_service.list_products(limit=3, order="price_desc")
    category_previews: list[dict] = []
    for category in categories[:4]:
        top_products = await product_service.list_products(limit=3, order="newest", category=category.lower())
        if top_products:
            category_previews.append({"category": category, "products": top_products})
    flags = await list_feature_flags(session)
    return templates.TemplateResponse(
        "products.html",
        {
            "request": request,
            "products": products,
            "categories": categories,
            "featured_highlights": highlighted,
            "selected_categories": selected_categories,
            "price_bounds": price_bounds,
            "price_filter": {"min": price_min, "max": price_max},
            "rating_filter": rating_param,
            "in_stock": in_stock,
            "category_previews": category_previews,
            "feature_flags": flags,
        },
    )


@app.get("/products/{product_id}", response_class=HTMLResponse, include_in_schema=False)
async def product_detail_page(
    product_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    templates = get_templates()
    product_service = ProductService(session)
    try:
        product = await product_service.get_product(product_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    catalog = await product_service.list_products(order="name")
    related_products = [
        item for item in catalog if item["category"] == product["category"] and item["id"] != product_id
    ][:4]
    if len(related_products) < 4:
        filler = [
            item
            for item in catalog
            if item["id"] != product_id and item not in related_products
        ][: 4 - len(related_products)]
        related_products.extend(filler)

    trending_products = [
        item for item in catalog if item["id"] != product_id and item not in related_products
    ][:4]
    flags = await list_feature_flags(session)

    return templates.TemplateResponse(
        "product_detail.html",
        {
            "request": request,
            "product": product,
            "related_products": related_products,
            "trending_products": trending_products,
            "feature_flags": flags,
        },
    )


@app.get("/cart", response_class=HTMLResponse, include_in_schema=False)
async def cart_page(request: Request, session: AsyncSession = Depends(get_session)):
    templates = get_templates()
    cart_service = CartService(session, resolve_session_key(request))
    cart_state = await cart_service.get_cart_state()
    flags = await list_feature_flags(session)
    return templates.TemplateResponse(
        "cart.html",
        {
            "request": request,
            "cart": cart_state,
            "items": cart_state["items"],
            "total": cart_state["total"],
            "feature_flags": flags,
        },
    )


@app.get("/checkout", response_class=HTMLResponse, include_in_schema=False)
async def checkout_page(request: Request, session: AsyncSession = Depends(get_session)):
    templates = get_templates()
    cart_service = CartService(session, resolve_session_key(request))
    cart_state = await cart_service.get_cart_state()
    flags = await list_feature_flags(session)
    return templates.TemplateResponse(
        "checkout.html",
        {
            "request": request,
            "cart": cart_state,
            "items": cart_state["items"],
            "total": cart_state["total"],
            "feature_flags": flags,
        },
    )


@app.post("/checkout", response_class=HTMLResponse, include_in_schema=False)
async def checkout_submit(
    request: Request,
    session: AsyncSession = Depends(get_session),
    name: str = Form(..., min_length=2),
    email: EmailStr = Form(...),
    address: str = Form(..., min_length=5),
):
    templates = get_templates()
    cart_service = CartService(session, resolve_session_key(request))
    cart_state = await cart_service.get_cart_state()
    flags = await list_feature_flags(session)

    def render(
        state: dict,
        *,
        status_code: int = 200,
        message: str | None = None,
        variant: str | None = None,
        order: dict | None = None,
        document_links: dict[str, str] | None = None,
    ):
        is_success = variant == "success" and message is not None
        context = {
            "request": request,
            "cart": state,
            "items": [] if is_success else state["items"],
            "total": 0 if is_success else state["total"],
            "feature_flags": flags,
            "checkout_message": message,
            "checkout_message_variant": variant,
            "order": order,
            "document_links": document_links,
        }
        return templates.TemplateResponse("checkout.html", context, status_code=status_code)

    if not cart_state["items"]:
        return render(
            cart_state,
            status_code=400,
            message="Your cart is empty. Add items before completing checkout.",
            variant="error",
        )

    pdf_service = PDFService(templates)
    order_service = OrderService(session=session, pdf_service=pdf_service)

    try:
        order, _ = await order_service.create_order(
            CustomerDetails(name=name, email=str(email), address=address),
            cart_state,
        )
    except ValueError as exc:
        return render(cart_state, status_code=400, message=str(exc), variant="error")

    await cart_service.clear_cart()
    cleared_state = await cart_service.get_cart_state()

    document_links = {
        "invoice": f"/api/docs/orders/{order.id}/invoice.pdf",
        "summary": f"/api/docs/orders/{order.id}/summary.pdf",
    }

    return render(
        cleared_state,
        message=f"Order {order.order_number} confirmed! We've sent a confirmation email to {order.customer_email}.",
        variant="success",
        order=order.to_dict(),
        document_links=document_links,
    )


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}


def configure_routes() -> None:
    """Import and register routers lazily to avoid circular dependencies."""
    from .api import admin, ai, auth, cart, checkout, docs, products, search

    app.include_router(products.router, prefix="/api/products", tags=["products"])
    app.include_router(search.router, prefix="/api/search", tags=["search"])
    app.include_router(cart.router, prefix="/api/cart", tags=["cart"])
    app.include_router(checkout.router, prefix="/api/checkout", tags=["checkout"])
    app.include_router(admin.router, prefix="/api/admin", tags=["feature-flags"])
    app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
    app.include_router(docs.router, prefix="/api/docs", tags=["documents"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])


configure_routes()
