from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from .core.config import settings, warn_obsolete_settings
from .core.db import get_session, init_db, shutdown_db
from .core.feature_flags import get_effective_flags
from .core.spaces import (
    DEFAULT_SPACE,
    SPACE_STATE_ATTR,
    WorkshopSpaceCookieMiddleware,
    cart_storage_key,
    resolve_workshop_space,
)
from .core.templatetags import format_currency
from .core.workshop import (
    ASSETS_MOUNT_PATH,
    bugs_global,
    build_assets_app,
    current_workshop_view,
    drift_global,
    planted_delay,
    workshop_view,
)
from .services.cart_service import CartService
from .services.product_service import ProductService
from .services.order_service import CustomerDetails, OrderService, checkout_summary
from .services.pdf_service import PDFService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise and tear down shared resources."""
    warn_obsolete_settings(settings)
    await init_db()
    try:
        yield
    finally:
        await shutdown_db()


app = FastAPI(
    title="AI Testing Workshop",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=settings.docs_url,
    redoc_url=settings.redoc_url,
    # Runs for every page and API route, including the routers that
    # configure_routes() adds below (design D1).
    dependencies=[Depends(resolve_workshop_space)],
)

# Appends the workshop_space cookie when the query parameter switched space.
app.add_middleware(WorkshopSpaceCookieMiddleware)

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

    # The per-stage stylesheet variants, served from memory (drift-coverage
    # Decision 5). A mount is not listed in /openapi.json and does not run the
    # app-level dependencies, so the stylesheet stays outside space resolution.
    # The stylesheet source left `static/`, so `/static/styles.css` is a 404.
    application.mount(ASSETS_MOUNT_PATH, build_assets_app(), name="assets")

    if templates_dir.exists():
        templates = Jinja2Templates(directory=str(templates_dir))
    else:
        templates = Jinja2Templates(directory=str(templates_dir))

    templates.env.filters["currency"] = format_currency
    templates.env.globals["brand_name"] = "Flowline Supply"
    # The layout reads settings.shared_mode for the space indicator (design D8).
    # The module-level object is registered, not a copy of its values, so the
    # attribute is read at render time.
    templates.env.globals["settings"] = settings
    # The request-scoped drift and bug helpers (drift-coverage Decision 1).
    # Both are proxies that read the view of the request being handled and
    # raise when none is set, so HTML that needs them can only be rendered from
    # a route that declares the `workshop_view` dependency. They are globals
    # rather than context values because macros imported with
    # `{% import ... as cards %}` see globals but not the render context.
    templates.env.globals["drift"] = drift_global
    templates.env.globals["bugs"] = bugs_global
    app.state.templates = templates


_mount_static_and_templates(app)


def get_templates() -> Jinja2Templates:
    return app.state.templates


#: The flags a page template still reads (drift-coverage task 5.10). Locator and
#: bug flags reach the markup only through the `drift` and `bugs` globals, so
#: they are kept out of the template context: a page that never sees them
#: cannot leak the active stage or the planted bugs.
PAGE_TEMPLATE_FLAGS: tuple[str, ...] = ("NEW_CART_UI", "MOBILE_UI_V1")


def page_feature_flags(flags: dict[str, bool]) -> dict[str, bool]:
    """The non-workshop flags a page template is given."""
    return {key: bool(flags.get(key)) for key in PAGE_TEMPLATE_FLAGS}


def displayed_summary(cart_state: dict) -> dict:
    """The checkout summary as the page shows it (design Decision 10).

    `checkout_summary` computes subtotal, tax and total exactly as the order
    does; `bugs.checkout_total` then applies `BUG_CHECKOUT_TOTAL` to the
    displayed copy only. The bug view comes from the request-scoped workshop
    view, which the `/checkout` routes declare as a dependency.
    """
    return current_workshop_view().bugs.checkout_total(checkout_summary(cart_state))


#: The checkout form's rules, the same as the checkout API's (``api/checkout.py``):
#: a valid email address, a name of at least 2 characters and an address of at
#: least 5. The form is validated inside ``POST /checkout`` and re-rendered with
#: one message per invalid field (WEB-006 AC-4 to AC-6 and AC-11).
CHECKOUT_NAME_MIN_LENGTH = 2
CHECKOUT_ADDRESS_MIN_LENGTH = 5
CHECKOUT_FIELD_MESSAGES: dict[str, str] = {
    "email": "Enter a valid email address, for example name@example.com.",
    "name": f"Enter your full name (at least {CHECKOUT_NAME_MIN_LENGTH} characters).",
    "address": f"Enter your shipping address (at least {CHECKOUT_ADDRESS_MIN_LENGTH} characters).",
}
#: The form-level alert above the fields when at least one field is invalid.
CHECKOUT_INVALID_MESSAGE = "Please correct the fields marked below and place your order again."

_EMAIL_ADDRESS = TypeAdapter(EmailStr)


def checkout_field_errors(name: str, email: str, address: str) -> tuple[dict[str, str], str]:
    """The message of every invalid checkout field, and the validated email address."""
    errors: dict[str, str] = {}
    try:
        email = str(_EMAIL_ADDRESS.validate_python(email))
    except ValidationError:
        errors["email"] = CHECKOUT_FIELD_MESSAGES["email"]
    if len(name) < CHECKOUT_NAME_MIN_LENGTH:
        errors["name"] = CHECKOUT_FIELD_MESSAGES["name"]
    if len(address) < CHECKOUT_ADDRESS_MIN_LENGTH:
        errors["address"] = CHECKOUT_FIELD_MESSAGES["address"]
    return errors, email


def request_space(request: Request) -> str:
    """The space that ``resolve_workshop_space`` stored for this request."""
    return getattr(request.state, SPACE_STATE_ATTR, DEFAULT_SPACE)


def resolve_session_key(request: Request) -> str:
    """The cart storage key of a page request (design D3).

    The session id still comes from the ``X-Session-ID`` header and then the
    ``session_id`` cookie; :func:`cart_storage_key` adds the shared
    ``workshop-demo`` fallback and the space prefix outside ``default``.
    """
    header_session_id = request.headers.get("x-session-id")
    cookie_session_id = request.cookies.get("session_id")
    return cart_storage_key(request_space(request), header_session_id or cookie_session_id)


@app.get(
    "/",
    response_class=HTMLResponse,
    include_in_schema=False,
    # Renders HTML through the `drift` and `bugs` globals (Decision 1).
    dependencies=[Depends(workshop_view)],
)
async def home_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
    flags: dict[str, bool] = Depends(get_effective_flags),
):
    templates = get_templates()
    product_service = ProductService(session)
    newest_products = await product_service.list_products(order="newest")
    featured_products = newest_products[:4]
    popular_products = sorted(newest_products, key=lambda item: item["inventory"], reverse=True)[:4]
    premium_picks = sorted(newest_products, key=lambda item: item["price"], reverse=True)[:4]
    categories = await product_service.list_categories()
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "request": request,
            "featured_products": featured_products,
            "popular_products": popular_products,
            "premium_picks": premium_picks,
            "newest_products": newest_products[:8],
            "categories": categories,
            "feature_flags": page_feature_flags(flags),
        },
    )


@app.get(
    "/products",
    response_class=HTMLResponse,
    include_in_schema=False,
    # Renders HTML through the `drift` and `bugs` globals (Decision 1), and is
    # one of the two catalogue responses `BUG_SLOW_RESPONSE` delays
    # (Decision 11). The delay runs before this route's own queries.
    dependencies=[Depends(workshop_view), Depends(planted_delay("catalogue"))],
)
async def products_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
    flags: dict[str, bool] = Depends(get_effective_flags),
):
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
    return templates.TemplateResponse(
        request,
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
            "feature_flags": page_feature_flags(flags),
        },
    )


@app.get(
    "/products/{product_id}",
    response_class=HTMLResponse,
    include_in_schema=False,
    # Renders HTML through the `drift` and `bugs` globals (Decision 1).
    dependencies=[Depends(workshop_view)],
)
async def product_detail_page(
    product_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    flags: dict[str, bool] = Depends(get_effective_flags),
):
    templates = get_templates()
    product_service = ProductService(session)
    # The id is parsed here, not by FastAPI, so an id that names no product -
    # unknown or not a number - gets the HTML not-found page from this route,
    # while `workshop_view` is active, instead of a JSON error.
    product = None
    if product_id.isascii() and product_id.isdigit() and len(product_id) <= 18:
        try:
            product = await product_service.get_product(int(product_id))
        except ValueError:
            product = None
    if product is None:
        return templates.TemplateResponse(
            request,
            "product_not_found.html",
            {"request": request, "feature_flags": page_feature_flags(flags)},
            status_code=404,
        )
    product_id = product["id"]

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

    return templates.TemplateResponse(
        request,
        "product_detail.html",
        {
            "request": request,
            "product": product,
            "related_products": related_products,
            "trending_products": trending_products,
            "feature_flags": page_feature_flags(flags),
        },
    )


@app.get(
    "/cart",
    response_class=HTMLResponse,
    include_in_schema=False,
    # Renders HTML through the `drift` and `bugs` globals (Decision 1).
    dependencies=[Depends(workshop_view)],
)
async def cart_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
    flags: dict[str, bool] = Depends(get_effective_flags),
):
    templates = get_templates()
    cart_service = CartService(session, resolve_session_key(request))
    cart_state = await cart_service.get_cart_state()
    return templates.TemplateResponse(
        request,
        "cart.html",
        {
            "request": request,
            "cart": cart_state,
            "items": cart_state["items"],
            "total": cart_state["total"],
            "feature_flags": page_feature_flags(flags),
        },
    )


@app.get(
    "/search/results",
    response_class=HTMLResponse,
    include_in_schema=False,
    # Renders HTML through the `drift` and `bugs` globals (Decision 1).
    dependencies=[Depends(workshop_view)],
)
async def search_results_fragment(
    request: Request,
    query: str = "",
    session: AsyncSession = Depends(get_session),
):
    """The search results fragment `app.js` inserts (drift-coverage Decision 6).

    The same `ProductService.search_products` as `GET /api/search/`, rendered
    with the product-card macro, so locator drift and the planted bugs reach
    search results exactly as they reach the listing. Hidden from the schema:
    it is a rendering detail of the shop, not a public API.
    """
    templates = get_templates()
    product_service = ProductService(session)
    products = await product_service.search_products(query)
    return templates.TemplateResponse(
        request,
        "components/search_results.html",
        {"request": request, "products": products, "query": query},
    )


@app.get(
    "/checkout",
    response_class=HTMLResponse,
    include_in_schema=False,
    # Renders HTML through the `drift` and `bugs` globals (Decision 1).
    dependencies=[Depends(workshop_view)],
)
async def checkout_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
    flags: dict[str, bool] = Depends(get_effective_flags),
):
    templates = get_templates()
    cart_service = CartService(session, resolve_session_key(request))
    cart_state = await cart_service.get_cart_state()
    return templates.TemplateResponse(
        request,
        "checkout.html",
        {
            "request": request,
            "cart": cart_state,
            "items": cart_state["items"],
            "total": cart_state["total"],
            "summary": displayed_summary(cart_state),
            "feature_flags": page_feature_flags(flags),
        },
    )


@app.post(
    "/checkout",
    response_class=HTMLResponse,
    include_in_schema=False,
    # Renders HTML through the `drift` and `bugs` globals (Decision 1).
    dependencies=[Depends(workshop_view)],
)
async def checkout_submit(
    request: Request,
    session: AsyncSession = Depends(get_session),
    flags: dict[str, bool] = Depends(get_effective_flags),
    # Validated below rather than by FastAPI, so an invalid field re-renders
    # the page with a message next to it instead of answering with JSON.
    name: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    team_size: str = Form(""),
    notes: str = Form(""),
):
    templates = get_templates()
    cart_service = CartService(session, resolve_session_key(request))
    cart_state = await cart_service.get_cart_state()

    def render(
        state: dict,
        *,
        status_code: int = 200,
        message: str | None = None,
        variant: str | None = None,
        order: dict | None = None,
        document_links: dict[str, str] | None = None,
        field_errors: dict[str, str] | None = None,
        form_values: dict[str, str] | None = None,
    ):
        is_success = variant == "success" and message is not None
        context = {
            "request": request,
            "cart": state,
            "items": [] if is_success else state["items"],
            "total": 0 if is_success else state["total"],
            "summary": displayed_summary(state),
            "feature_flags": page_feature_flags(flags),
            "checkout_message": message,
            "checkout_message_variant": variant,
            "order": order,
            "document_links": document_links,
            "field_errors": field_errors or {},
            "form_values": form_values,
        }
        return templates.TemplateResponse(request, "checkout.html", context, status_code=status_code)

    field_errors, email = checkout_field_errors(name, email, address)
    if field_errors:
        return render(
            cart_state,
            status_code=422,
            message=CHECKOUT_INVALID_MESSAGE,
            variant="error",
            field_errors=field_errors,
            form_values={
                "email": email,
                "name": name,
                "address": address,
                "team_size": team_size,
                "notes": notes,
            },
        )

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
            CustomerDetails(name=name, email=email, address=address),
            cart_state,
            space=request_space(request),
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
    # The setting is read on every request, so the reported version always
    # reflects the current configuration and never a value frozen at import.
    return {"status": "ok", "version": settings.app_version}


def configure_routes() -> None:
    """Import and register routers lazily to avoid circular dependencies."""
    from .api import admin, ai, auth, cart, checkout, docs, products, search, workshop

    app.include_router(products.router, prefix="/api/products", tags=["products"])
    app.include_router(search.router, prefix="/api/search", tags=["search"])
    app.include_router(cart.router, prefix="/api/cart", tags=["cart"])
    app.include_router(checkout.router, prefix="/api/checkout", tags=["checkout"])
    # The workshop control endpoints stay callable but leave the published
    # schema (drift-coverage Decision 13): an agent exploring `/openapi.json`,
    # `/docs` or `/redoc` must not be handed the stage, the planted bugs or the
    # switches that change them. `/search/results` and the `/assets` mount are
    # out of the schema for the same reason, at their own definitions.
    app.include_router(
        admin.router, prefix="/api/admin", tags=["feature-flags"], include_in_schema=False
    )
    app.include_router(ai.router, prefix="/api/ai", tags=["ai"])
    app.include_router(docs.router, prefix="/api/docs", tags=["documents"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(
        workshop.router, prefix="/api/workshop", tags=["workshop"], include_in_schema=False
    )


configure_routes()
