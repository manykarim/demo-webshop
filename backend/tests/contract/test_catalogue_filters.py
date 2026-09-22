"""Regression tests for the catalogue filters (acceptance-conformance, WEB-002).

WEB-002_AC-3, AC-6 and AC-9: the price sliders span the exact lowest and
highest catalogue prices, their values are shown and submitted in cents, and
the default range therefore excludes no product - before the fix, the bounds
were rounded to whole dollars, so the cheapest product ($39.50) dropped out of
every filtered listing. WEB-002_AC-6 also needs a product count that reflects
the filtered results.

Every render repeats in stages 1 to 4: the fix touches ``products.html`` and
``app.js``, and visible text must be identical in every stage. Elements are
found by tag, ``for`` and ``aria-label`` - the stable surface - never by a
covered hook.
"""
from __future__ import annotations

import re

import pytest
from bs4 import Tag

from backend.app.core.workshop import STAGES

from .conftest import STAGE_FLAGS
from .hooks import soup_of
from .semantic import normalize_text

GRID_HEADING = "All products"
COUNT = re.compile(r"^(\d+) (products?)$")


@pytest.fixture(scope="module")
def catalogue(contract_client) -> list[dict]:
    response = contract_client.get("/api/products/")
    response.raise_for_status()
    return response.json()["items"]


def slider(html: str, label: str) -> Tag:
    found = soup_of(html).find("input", attrs={"type": "range", "aria-label": label})
    assert found is not None, f"no {label!r} slider"
    return found


def output_for(html: str, slider_id: str) -> str:
    found = soup_of(html).find("output", attrs={"for": slider_id})
    assert found is not None, f"no output for {slider_id!r}"
    return normalize_text(found.get_text(" "))


def grid_section(html: str) -> Tag:
    heading = soup_of(html).find(lambda tag: tag.name == "h2" and normalize_text(tag.get_text(" ")) == GRID_HEADING)
    assert heading is not None, "no 'All products' heading"
    section = heading.find_parent("section")
    assert section is not None
    return section


def grid_names(html: str) -> list[str]:
    return [
        normalize_text(article.find(["h2", "h3", "h4"]).get_text(" "))
        for article in grid_section(html).find_all("article")
    ]


def product_count(html: str) -> tuple[int, str]:
    counts = [
        match
        for paragraph in grid_section(html).find_all("p")
        if (match := COUNT.match(normalize_text(paragraph.get_text(" "))))
    ]
    assert len(counts) == 1, f"expected one product count in the grid section, found {len(counts)}"
    return int(counts[0].group(1)), counts[0].group(2)


@pytest.mark.parametrize("stage", STAGES)
def test_sliders_span_the_exact_price_range(render, catalogue, stage: int) -> None:
    prices = [float(product["price"]) for product in catalogue]
    low, high = f"{min(prices):.2f}", f"{max(prices):.2f}"
    html = render("/products", STAGE_FLAGS[stage]).text

    for label in ("Minimum price", "Maximum price"):
        element = slider(html, label)
        assert (element["min"], element["max"], element["step"]) == (low, high, "any")
    assert slider(html, "Minimum price")["value"] == low
    assert slider(html, "Maximum price")["value"] == high
    assert output_for(html, slider(html, "Minimum price")["id"]) == low
    assert output_for(html, slider(html, "Maximum price")["id"]) == high
    hidden = {
        field["name"]: field["value"]
        for field in soup_of(html).find_all("input", attrs={"type": "hidden"})
        if field.get("name") in ("price_min", "price_max")
    }
    assert hidden == {"price_min": low, "price_max": high}


@pytest.mark.parametrize("stage", STAGES)
def test_the_default_range_keeps_the_cheapest_product(render, catalogue, stage: int) -> None:
    """Submitting the filter form unchanged lists every product, the cheapest included."""
    cheapest = min(catalogue, key=lambda product: float(product["price"]))
    prices = [float(product["price"]) for product in catalogue]
    query = f"/products?price_min={min(prices):.2f}&price_max={max(prices):.2f}&category={cheapest['category']}"
    html = render(query, STAGE_FLAGS[stage]).text

    expected = sorted(product["name"] for product in catalogue if product["category"] == cheapest["category"])
    assert sorted(grid_names(html)) == expected
    assert cheapest["name"] in grid_names(html)


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize(
    ("query", "category"),
    [("/products", None), ("/products?category=Audio", "Audio"), ("/products?category=Imaging", "Imaging")],
)
def test_the_product_count_reflects_the_grid(render, catalogue, stage: int, query: str, category: str | None) -> None:
    html = render(query, STAGE_FLAGS[stage]).text
    expected = len([product for product in catalogue if category is None or product["category"] == category])

    assert len(grid_names(html)) == expected
    assert product_count(html) == (expected, "product" if expected == 1 else "products")


def test_the_product_count_of_an_empty_result(render) -> None:
    html = render("/products?category=Audio&price_min=100&price_max=200", STAGE_FLAGS[1]).text

    assert grid_names(html) == []
    assert product_count(html) == (0, "products")


@pytest.mark.parametrize("stage", STAGES)
def test_the_product_count_is_no_status_region(render, stage: int) -> None:
    """The count re-renders only on a full submit: no live region, never ``role="status"``."""
    html = render("/products", STAGE_FLAGS[stage]).text
    paragraph = next(
        paragraph
        for paragraph in grid_section(html).find_all("p")
        if COUNT.match(normalize_text(paragraph.get_text(" ")))
    )

    assert paragraph.get("role") is None
    assert paragraph.get("id") is None
    assert paragraph.get("class") is None
    assert (paragraph.get("data-test") == "product-count") == (stage in (1, 2))
