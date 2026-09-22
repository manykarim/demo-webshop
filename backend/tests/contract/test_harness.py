"""The contract suite's own harness check (drift-coverage task 4.1).

Everything the matrix relies on is verified here once: the client renders, the
flag seam really selects the stage, SKUs resolve to the seeded product ids, and
all storage lives inside pytest's temporary directory rather than in the
repository.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from .conftest import STAGE_FLAGS
from .hooks import data_test_multiset, extract_hooks


@pytest.mark.parametrize("stage", [1, 2])
def test_home_renders_in_stage(render, stage: int) -> None:
    """``/`` renders in stages 1 and 2, and the seam really picks the stage."""
    response = render("/", STAGE_FLAGS[stage])

    assert response.status_code == 200
    classes = extract_hooks(response.text).classes
    # Stage 2 renames the product card block; the `product-card` *test hook*
    # survives it, so the class names are what tells the two stages apart.
    assert ("item-card" in classes) is (stage == 2)
    assert ("product-card" in classes) is (stage == 1)
    # Both stages keep every data-test attribute.
    assert data_test_multiset(response.text)["product-card"] > 0


@pytest.mark.parametrize(
    ("sku", "product_id"),
    [
        ("PUL-RNG-003", 3),
        ("NIM-LGT-004", 4),
        ("ATL-DSK-005", 5),
        ("CAS-BOT-012", 12),
    ],
)
def test_product_id_by_sku(
    product_id_by_sku: Callable[[str], int], sku: str, product_id: int
) -> None:
    """The seeded catalogue maps the matrix SKUs to the expected ids."""
    assert product_id_by_sku(sku) == product_id


def test_storage_stays_inside_the_pytest_temporary_directory(
    contract_client, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Neither the database nor the PDF directory escapes into the repository."""
    from sqlalchemy.engine import make_url

    from backend.app.core.config import settings
    from backend.app.core.db import get_engine

    base = tmp_path_factory.getbasetemp().resolve()
    database_path = Path(make_url(str(get_engine().url)).database).resolve()
    pdf_output_dir = Path(settings.pdf_output_dir).resolve()

    assert database_path.is_relative_to(base), database_path
    assert pdf_output_dir.is_relative_to(base), pdf_output_dir


def test_cart_helper_fills_the_cart(render, add_to_cart) -> None:
    """``add_to_cart`` puts items in the session the page render then uses."""
    session_id = "contract-harness-cart"
    add_to_cart(session_id, (("PUL-RNG-003", 2),))

    response = render("/cart", STAGE_FLAGS[1], session_id)

    assert response.status_code == 200
    assert "Pulse Bio Ring" in response.text


def test_subprocess_env_points_at_the_harness_storage(
    subprocess_env: dict[str, str], tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A fresh interpreter would use the same temporary storage."""
    base = tmp_path_factory.getbasetemp().resolve()
    url = subprocess_env["WORKSHOP_DATABASE_URL"]
    _, _, location = url.partition(":///")

    assert Path(location).resolve().is_relative_to(base), url
    assert Path(subprocess_env["WORKSHOP_PDF_OUTPUT_DIR"]).resolve().is_relative_to(base)
