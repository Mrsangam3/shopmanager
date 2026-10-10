from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Product, Purchase, Role, Supplier, User
from app.purchases.services import PurchaseError, create_purchase


def make_supplier(app):
    with app.app_context():
        supplier = Supplier(name="Acme Traders")
        db.session.add(supplier)
        db.session.commit()
        return supplier.id


def test_cost_becomes_a_weighted_average(app, make_user, make_product):
    owner = make_user(Role.OWNER)
    pid = make_product(quantity=10, cost="20.00")
    supplier_id = make_supplier(app)
    with app.app_context():
        create_purchase(db.session.get(User, owner["id"]), supplier_id,
                        [{"product_id": pid, "quantity": 10, "unit_cost": Decimal("30.00")}])
        product = db.session.get(Product, pid)
        assert product.quantity == 20
        assert product.cost == Decimal("25.00")      # (10*20 + 10*30) / 20


def test_two_lines_for_one_product_average_in_order(app, make_user, make_product):
    owner = make_user(Role.OWNER)
    pid = make_product(quantity=10, cost="20.00")
    supplier_id = make_supplier(app)
    with app.app_context():
        create_purchase(db.session.get(User, owner["id"]), supplier_id, [
            {"product_id": pid, "quantity": 10, "unit_cost": Decimal("30.00")},
            {"product_id": pid, "quantity": 20, "unit_cost": Decimal("30.00")},
        ])
        product = db.session.get(Product, pid)
        assert product.quantity == 40
        assert product.cost == Decimal("27.50")      # (20*25 + 20*30) / 40


def test_failed_purchase_changes_nothing(app, make_user, make_product):
    owner = make_user(Role.OWNER)
    good = make_product(sku="G", quantity=10, cost="20.00")
    archived = make_product(sku="X", active=False)
    supplier_id = make_supplier(app)
    with app.app_context():
        user = db.session.get(User, owner["id"])
        with pytest.raises(PurchaseError):
            create_purchase(user, supplier_id, [
                {"product_id": good, "quantity": 5, "unit_cost": Decimal("30.00")},
                {"product_id": archived, "quantity": 1, "unit_cost": Decimal("1.00")},
            ])
        product = db.session.get(Product, good)
        assert product.quantity == 10
        assert product.cost == Decimal("20.00")
        assert db.session.scalar(db.select(db.func.count(Purchase.id))) == 0