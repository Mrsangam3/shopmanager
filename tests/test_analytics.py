from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.analytics.routes import period_totals
from app.extensions import db
from app.models import Product, Role, User
from app.sales.services import create_sale


def test_profit_uses_the_cost_at_the_time_of_sale(app, make_user, make_product):
    owner = make_user(Role.OWNER)
    pid = make_product(quantity=10, price="10.00", cost="6.00")
    with app.app_context():
        create_sale(db.session.get(User, owner["id"]), {pid: 2})

        # the product's cost changes AFTER the sale
        product = db.session.get(Product, pid)
        product.cost = Decimal("9.00")
        db.session.commit()

        now = datetime.now(timezone.utc).replace(tzinfo=None)   # stored times are naive UTC
        totals = period_totals(now - timedelta(days=1), now + timedelta(days=1))
        assert totals["revenue"] == Decimal("20.00")
        assert totals["profit"] == Decimal("8.00")      # 20 - (2 * 6), not 20 - (2 * 9)
        assert totals["orders"] == 1