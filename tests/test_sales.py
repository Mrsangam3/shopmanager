from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Product, Role, Sale, User
from app.sales.services import SaleError, create_sale


def quantity_of(product_id):
    return db.session.get(Product, product_id).quantity


def sale_count():
    return db.session.scalar(db.select(db.func.count(Sale.id)))


def test_sale_deducts_stock_and_snapshots_price_and_cost(app, make_user, make_product):
    owner = make_user(Role.OWNER)
    pid = make_product(quantity=10, price="10.00", cost="6.00")
    with app.app_context():
        sale = create_sale(db.session.get(User, owner["id"]), {pid: 3})
        assert sale.total == Decimal("30.00")
        assert sale.items[0].unit_price == Decimal("10.00")
        assert sale.items[0].unit_cost == Decimal("6.00")
        assert quantity_of(pid) == 7


def test_last_item_cannot_be_sold_twice(app, make_user, make_product):
    owner = make_user(Role.OWNER)
    pid = make_product(quantity=1)
    with app.app_context():
        user = db.session.get(User, owner["id"])
        create_sale(user, {pid: 1})
        with pytest.raises(SaleError):
            create_sale(user, {pid: 1})
        assert quantity_of(pid) == 0      # never negative
        assert sale_count() == 1


def test_failed_sale_changes_nothing(app, make_user, make_product):
    owner = make_user(Role.OWNER)
    plenty = make_product(sku="A", quantity=10)
    scarce = make_product(sku="B", quantity=1)
    with app.app_context():
        user = db.session.get(User, owner["id"])
        with pytest.raises(SaleError):
            create_sale(user, {plenty: 2, scarce: 5})
        assert quantity_of(plenty) == 10   # the first deduction was rolled back
        assert quantity_of(scarce) == 1
        assert sale_count() == 0


def test_archived_product_cannot_be_sold(app, make_user, make_product):
    owner = make_user(Role.OWNER)
    pid = make_product(quantity=5, active=False)
    with app.app_context():
        with pytest.raises(SaleError):
            create_sale(db.session.get(User, owner["id"]), {pid: 1})
        assert sale_count() == 0


def test_client_cannot_choose_the_price(app, client, make_user, make_product, login):
    cashier = make_user(Role.CASHIER)
    pid = make_product(price="50.00", quantity=5)
    login(cashier["email"])
    response = client.post("/sales/new", data={
        "product_id": [str(pid)], "quantity": ["2"], "unit_price": ["0.01"]})
    assert response.status_code == 302
    with app.app_context():
        sale = db.session.scalars(db.select(Sale)).one()
        assert sale.total == Decimal("100.00")
        assert quantity_of(pid) == 3


def test_huge_quantity_is_rejected(app, client, make_user, make_product, login):
    cashier = make_user(Role.CASHIER)
    pid = make_product(quantity=5)
    login(cashier["email"])
    response = client.post("/sales/new", data={
        "product_id": [str(pid)], "quantity": ["999999"]})
    assert response.status_code == 200
    assert b"between 1 and" in response.data
    with app.app_context():
        assert quantity_of(pid) == 5
        assert sale_count() == 0


def test_cashier_cannot_open_someone_elses_invoice(app, client, make_user, make_product, login):
    owner = make_user(Role.OWNER)
    cashier = make_user(Role.CASHIER)
    pid = make_product(quantity=5)
    with app.app_context():
        sale_id = create_sale(db.session.get(User, owner["id"]), {pid: 1}).id
    login(cashier["email"])
    assert client.get(f"/sales/{sale_id}").status_code == 403