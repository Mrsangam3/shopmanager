import os


def _database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///shop.db")
    # some hosts hand out "postgres://", which SQLAlchemy no longer accepts
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    # name the driver explicitly (psycopg 3) instead of relying on a default
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,   # test a connection before using it (hosts drop idle ones)
        "pool_recycle": 300,
    }
    SESSION_COOKIE_SAMESITE = "Lax"   # blocks cookies on cross-site POSTs
    SESSION_COOKIE_HTTPONLY = True    # JavaScript can't read the cookie
    # If your old config.py had a different time zone, put it here.
    SHOP_TIMEZONE = os.environ.get("SHOP_TIMEZONE", "Asia/Kolkata")
    PROXY_FIX = False
    REQUIRE_STRONG_SECRET = False


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True      # cookie only travels over HTTPS
    REMEMBER_COOKIE_SECURE = True
    REMEMBER_COOKIE_HTTPONLY = True
    PROXY_FIX = True                  # trust the hosting platform's proxy headers
    REQUIRE_STRONG_SECRET = True      # refuse to start with a weak secret


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False          # tests that need CSRF switch it back on
    RATELIMIT_ENABLED = False
    SHOP_TIMEZONE = "UTC"


def get_config():
    """Pick the config from the APP_ENV environment variable."""
    return ProductionConfig if os.environ.get("APP_ENV") == "production" else Config