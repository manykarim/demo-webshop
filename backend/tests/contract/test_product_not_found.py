"""Regression tests for the product detail route's not-found render (WEB-003_AC-9).

Before the fix, ``/products/9999`` answered with the JSON body
``{"detail": "Product not found"}`` and ``/products/abc`` with a JSON 422, so a
visitor who followed a stale or mistyped link saw raw JSON. The route now
parses the id itself and renders ``product_not_found.html`` with status 404
while ``workshop_view`` is active - no global exception handler - so the page
drifts like every other render (drift contract items (c), (e) and (g)).

The render is also a ``COVERED_PAGES`` entry (``detail-not-found``), so the
stage matrix of ``test_stage_contract.py`` checks it too; the tests here pin
what a visitor sees, in every stage, and the API's JSON errors, which must not
change.
"""
from __future__ import annotations

import pytest

from backend.app.core.workshop import STAGES

from .conftest import STAGE_FLAGS
from .hooks import soup_of
from .semantic import normalize_text

UNKNOWN_IDS = ("9999", "abc", "0", "-1", "1.5", "99999999999999999999999")


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("product_id", UNKNOWN_IDS)
def test_unknown_product_renders_the_not_found_page(render, stage: int, product_id: str) -> None:
    response = render(f"/products/{product_id}", STAGE_FLAGS[stage])

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    soup = soup_of(response.text)
    assert [normalize_text(h1.get_text(" ")) for h1 in soup.find_all("h1")] == ["Product not found"]
    main = soup.find("main")
    assert main is not None, "the not-found page renders without the site layout"
    assert "couldn't find a product" in normalize_text(main.get_text(" "))
    assert main.find("a", href="/products") is not None, "no way back to the catalogue"
    # No product detail content: no purchase action and no price.
    assert main.find("button") is None
    assert "$" not in normalize_text(main.get_text(" "))
    # The add-to-cart confirmation stays the only status region.
    assert len(soup.find_all(attrs={"role": "status"})) == 1
    hooks = soup.find_all(attrs={"data-test": "product-not-found"})
    assert len(hooks) == (1 if stage in (1, 2) else 0)


@pytest.mark.parametrize("stage", (1, 2))
def test_the_not_found_text_is_identical_in_stages_1_and_2(render, stage: int) -> None:
    def text(flags) -> str:
        soup = soup_of(render("/products/9999", flags).text)
        return normalize_text(soup.find("main").get_text(" "))

    assert text(STAGE_FLAGS[stage]) == text(STAGE_FLAGS[1])


def test_a_known_product_still_renders(render) -> None:
    response = render("/products/1", STAGE_FLAGS[1])

    assert response.status_code == 200
    assert [normalize_text(h1.get_text(" ")) for h1 in soup_of(response.text).find_all("h1")] == [
        "Aurora Neural Headphones"
    ]


def test_the_api_keeps_its_json_errors(contract_client) -> None:
    response = contract_client.get("/api/products/9999")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
