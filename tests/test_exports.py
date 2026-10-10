import pytest

from app.exports.routes import safe
from app.models import Role


@pytest.mark.parametrize("raw, expected", [
    ("=1+1", "'=1+1"),
    ("+cmd", "'+cmd"),
    ("-5", "'-5"),
    ("@SUM(A1)", "'@SUM(A1)"),
    ("Rice", "Rice"),
    (None, ""),
])
def test_safe_neutralises_spreadsheet_formulas(raw, expected):
    assert safe(raw) == expected


def test_inventory_export_is_safe_and_excel_friendly(client, make_user, make_product, login):
    owner = make_user(Role.OWNER)
    make_product(name="=1+1", sku="F-1")
    make_product(name="Rice, 5kg", sku="R-1")
    login(owner["email"])
    response = client.get("/exports/inventory.csv")
    text = response.get_data(as_text=True)
    assert response.mimetype == "text/csv"
    assert text.startswith("\ufeff")          # BOM, so Excel reads UTF-8
    assert "'=1+1" in text                    # formula neutralised
    assert '"Rice, 5kg"' in text              # comma safely quoted


def test_sales_export_rejects_a_backwards_range(client, make_user, login):
    owner = make_user(Role.OWNER)
    login(owner["email"])
    response = client.get("/exports/sales.csv?from=2026-10-10&to=2026-01-01")
    assert response.status_code == 302
    assert "/exports/" in response.headers["Location"]


def test_sales_export_rejects_an_overlong_range(client, make_user, login):
    owner = make_user(Role.OWNER)
    login(owner["email"])
    response = client.get("/exports/sales.csv?from=2020-01-01&to=2026-01-01")
    assert response.status_code == 302


def test_export_requires_a_manager(client, make_user, login):
    cashier = make_user(Role.CASHIER)
    login(cashier["email"])
    assert client.get("/exports/sales.csv?from=2026-01-01&to=2026-01-31").status_code == 403