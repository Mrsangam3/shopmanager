from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Product, Role


def form(**overrides):
    data = {"name": "Rice", "sku": "rice-1", "category_id": "", "price": "55.50",
            "cost": "40.00", "quantity": "10", "reorder_level": "3"}
    data.update(overrides)
    return data


def product_count():
    return db.session.scalar(db.select(db.func.count(Product.id)))


def test_manager_can_add_a_product(app, client, make_user, login):
    manager = make_user(Role.MANAGER)
    login(manager["email"])
    response = client.post("/inventory/products/new", data=form())
    assert response.status_code == 302
    with app.app_context():
        product = db.session.scalar(db.select(Product).filter_by(sku="RICE-1"))
        assert product is not None
        assert product.price == Decimal("55.50")


def test_cashier_cannot_add_a_product(app, client, make_user, login):
    cashier = make_user(Role.CASHIER)
    login(cashier["email"])
    assert client.post("/inventory/products/new", data=form()).status_code == 403
    with app.app_context():
        assert product_count() == 0


def test_duplicate_sku_is_rejected(app, client, make_user, make_product, login):
    owner = make_user(Role.OWNER)
    make_product(sku="RICE-1")
    login(owner["email"])
    response = client.post("/inventory/products/new", data=form())
    assert response.status_code == 200
    assert b"already used" in response.data
    with app.app_context():
        assert product_count() == 1


@pytest.mark.parametrize("field, value", [
    ("price", "-1"), ("price", "abc"), ("quantity", "-5"), ("quantity", "1.5"),
])
def test_bad_numbers_are_rejected(app, client, make_user, login, field, value):
    owner = make_user(Role.OWNER)
    login(owner["email"])
    response = client.post("/inventory/products/new", data=form(**{field: value}))
    assert response.status_code == 200
    with app.app_context():
        assert product_count() == 0


def test_archiving_hides_a_product_from_the_list(client, make_user, make_product, login):
    owner = make_user(Role.OWNER)
    pid = make_product(name="Visible Thing")
    login(owner["email"])

    row = b"<td>Visible Thing</td>"
    assert row in client.get("/inventory/").data

    client.post(f"/inventory/products/{pid}/toggle")

    # the "archived" flash message mentions the name, so look for the table row, not the bare name
    assert row not in client.get("/inventory/").data