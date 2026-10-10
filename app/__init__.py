from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request
from flask_login import current_user
from sqlalchemy import func
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config
from app.extensions import db, login_manager, migrate, csrf, limiter

# Scripts and styles come only from our own site and the jsDelivr CDN.
# 'unsafe-inline' is needed because some pages have inline <script> blocks;
# nonces would be the stricter upgrade.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "img-src 'self' data:; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self' https://cdn.jsdelivr.net; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def create_app(config_class=None):
    app = Flask(__name__)
    app.config.from_object(config_class or get_config())

    if app.config.get("REQUIRE_STRONG_SECRET"):
        key = app.config["SECRET_KEY"]
        if key == "dev-only-change-me" or len(key) < 32:
            raise RuntimeError("Set a strong SECRET_KEY (32+ characters) in production.")

    if app.config.get("PROXY_FIX"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from app import models  # noqa: F401

    from app.main.routes import main
    from app.auth.routes import auth
    from app.inventory.routes import inventory
    from app.sales.routes import sales
    from app.purchases.routes import purchases
    from app.analytics.routes import analytics
    from app.exports.routes import exports
    app.register_blueprint(main)
    app.register_blueprint(auth)
    app.register_blueprint(inventory)
    app.register_blueprint(sales)
    app.register_blueprint(purchases)
    app.register_blueprint(analytics)
    app.register_blueprint(exports)

    from app.cli import register_cli
    register_cli(app)

    # ---------- security headers ----------
    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy",
                                    "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("Content-Security-Policy", CSP)
        if request.is_secure:   # HSTS only makes sense over HTTPS
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    # ---------- friendly error pages ----------
    def render_error(code, title, message):
        return render_template("errors/error.html", code=code, title=title,
                               message=message), code

    @app.errorhandler(400)
    def bad_request(e):
        return render_error(400, "Request rejected",
                            "Your session may have expired. Go back, refresh the page and try again.")

    @app.errorhandler(403)
    def forbidden(e):
        return render_error(403, "Access denied",
                            "You don't have permission to view this page.")

    @app.errorhandler(404)
    def not_found(e):
        return render_error(404, "Page not found",
                            "The page you are looking for doesn't exist.")

    @app.errorhandler(429)
    def too_many_requests(e):
        return render_error(429, "Too many attempts",
                            "Please wait a minute and try again.")

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()   # leave the database session clean
        return render_error(500, "Something went wrong",
                            "The error has been logged. Please try again.")

    # ---------- template helpers ----------
    @app.template_filter("localtime")
    def localtime(dt, fmt="%d %b %Y, %I:%M %p"):
        """Stored times are UTC; show them in the shop's timezone."""
        if dt is None:
            return ""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(app.config["SHOP_TIMEZONE"])).strftime(fmt)

    @app.context_processor
    def inject_low_stock_count():
        """Make `low_stock_count` available in every template."""
        if not current_user.is_authenticated:
            return {}
        from app.models import Product
        try:
            count = db.session.scalar(
                db.select(func.count(Product.id))
                .where(Product.is_active.is_(True), Product.is_low_stock))
        except Exception:
            db.session.rollback()   # never let the badge break an error page
            return {}
        return {"low_stock_count": count}

    return app