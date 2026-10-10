from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db
from app.models import Product, Role, User
from config import TestingConfig


@pytest.fixture()
def app():
    """A fresh app with an empty in-memory database for every test."""
    app = create_app(TestingConfig)
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(app):
    """Create a user and return {"id", "email", "password"}."""
    def _make(role=Role.CASHIER, email=None, password="password123"):
        email = email or f"{role}@test.com"
        with app.app_context():
            user = User(name=role.title(), email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            return {"id": user.id, "email": email, "password": password}
    return _make


@pytest.fixture()
def make_product(app):
    """Create a product and return its id."""
    counter = {"n": 0}

    def _make(name="Widget", sku=None, price="10.00", cost="6.00",
              quantity=5, reorder_level=2, active=True):
        counter["n"] += 1
        sku = sku or f"SKU-{counter['n']}"
        with app.app_context():
            product = Product(name=name, sku=sku, price=Decimal(price),
                              cost=Decimal(cost), quantity=quantity,
                              reorder_level=reorder_level, is_active=active)
            db.session.add(product)
            db.session.commit()
            return product.id
    return _make


@pytest.fixture()
def login(client):
    def _login(email, password="password123"):
        return client.post("/auth/login", data={"email": email, "password": password})
    return _login