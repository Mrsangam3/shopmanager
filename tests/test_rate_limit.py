from app import create_app
from app.extensions import db, limiter
from config import TestingConfig


class LimiterOn(TestingConfig):
    RATELIMIT_ENABLED = True


def test_sixth_failed_login_is_blocked():
    app = create_app(LimiterOn)
    with app.app_context():
        db.create_all()
    client = app.test_client()
    ip = {"REMOTE_ADDR": "203.0.113.9"}   # a private test address, so other tests don't share its counter

    codes = [
        client.post("/auth/login",
                    data={"email": "x@test.com", "password": "wrong"},
                    environ_overrides=ip).status_code
        for _ in range(6)
    ]

    limiter.reset()   # clear the counters so other tests are unaffected
    with app.app_context():
        db.session.remove()
        db.drop_all()

    assert codes == [401, 401, 401, 401, 401, 429]