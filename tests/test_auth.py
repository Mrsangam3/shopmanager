import pytest

from app.extensions import db
from app.models import Role, User

CASHIER_FORBIDDEN = [
    "/inventory/products/new", "/inventory/reorder", "/purchases/",
    "/purchases/new", "/purchases/suppliers", "/analytics/",
    "/exports/", "/exports/inventory.csv", "/auth/employees",
]

OWNER_ALLOWED = [
    "/dashboard", "/inventory/", "/inventory/reorder", "/purchases/",
    "/purchases/suppliers", "/analytics/", "/exports/", "/auth/employees",
    "/sales/", "/sales/new",
]


@pytest.mark.parametrize("url", ["/dashboard", "/inventory/", "/sales/new", "/sales/"])
def test_anonymous_users_are_sent_to_login(client, url):
    response = client.get(url)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_wrong_password_gets_generic_error(client, make_user):
    user = make_user(Role.CASHIER)
    response = client.post("/auth/login",
                           data={"email": user["email"], "password": "wrong-password"})
    assert response.status_code == 401
    assert b"Invalid email or password" in response.data


def test_unknown_email_gets_the_same_error(client):
    response = client.post("/auth/login",
                           data={"email": "nobody@test.com", "password": "whatever"})
    assert response.status_code == 401
    assert b"Invalid email or password" in response.data


def test_login_redirect_cannot_leave_the_site(client, make_user):
    user = make_user(Role.OWNER)
    response = client.post("/auth/login?next=//evil.example.com",
                           data={"email": user["email"], "password": user["password"]})
    assert response.status_code == 302
    assert "evil.example.com" not in response.headers["Location"]
    assert response.headers["Location"].endswith("/dashboard")


def test_logout_requires_post(client, make_user, login):
    user = make_user(Role.OWNER)
    login(user["email"])
    assert client.get("/auth/logout").status_code == 405


@pytest.mark.parametrize("url", CASHIER_FORBIDDEN)
def test_cashier_is_blocked_from_manager_pages(client, make_user, login, url):
    user = make_user(Role.CASHIER)
    login(user["email"])
    assert client.get(url).status_code == 403


@pytest.mark.parametrize("url", OWNER_ALLOWED)
def test_owner_can_open_every_page(client, make_user, login, url):
    user = make_user(Role.OWNER)
    login(user["email"])
    assert client.get(url).status_code == 200


def test_owner_cannot_create_another_owner_through_the_form(app, client, make_user, login):
    owner = make_user(Role.OWNER)
    login(owner["email"])
    client.post("/auth/employees", data={
        "name": "Sneaky", "email": "sneaky@test.com",
        "role": "owner", "password": "password123"})
    with app.app_context():
        assert db.session.scalar(db.select(User).filter_by(email="sneaky@test.com")) is None