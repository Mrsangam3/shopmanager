from app import create_app
from config import TestingConfig


def test_security_headers_are_set(client):
    response = client.get("/auth/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_hsts_is_sent_only_over_https(client):
    assert "Strict-Transport-Security" not in client.get("/auth/login").headers
    secure = client.get("/auth/login", base_url="https://localhost")
    assert "Strict-Transport-Security" in secure.headers


def test_custom_404_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert b"Page not found" in response.data


def test_post_without_csrf_token_is_rejected():
    class CsrfOn(TestingConfig):
        WTF_CSRF_ENABLED = True

    app = create_app(CsrfOn)
    response = app.test_client().post(
        "/auth/login", data={"email": "a@test.com", "password": "x"})
    assert response.status_code == 400