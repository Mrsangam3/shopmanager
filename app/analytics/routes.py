from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, request, current_app
from sqlalchemy import func

from app.extensions import db
from app.models import Sale, SaleItem, Product, User, Role
from app.decorators import roles_required

analytics = Blueprint("analytics", __name__, url_prefix="/analytics")

MANAGERS = (Role.OWNER, Role.MANAGER)
RANGES = {7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days", 365: "Last 12 months"}
CENT = Decimal("0.01")


# ---------- helpers ----------

def money(value):
    """Normalise whatever the database returns into an exact 2-place Decimal."""
    return Decimal(str(value or 0)).quantize(CENT)


def shop_tz():
    return ZoneInfo(current_app.config["SHOP_TIMEZONE"])


def day_start_utc(day):
    """Midnight at the start of `day` in the shop's time zone, as naive UTC
    (the form in which we store times)."""
    local = datetime.combine(day, time.min, tzinfo=shop_tz())
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def to_local_date(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(shop_tz()).date()


def period_totals(start, end):
    """Revenue, cost, profit and order count for sales in [start, end)."""
    in_range = (Sale.created_at >= start, Sale.created_at < end)

    revenue, orders = db.session.execute(
        db.select(func.coalesce(func.sum(Sale.total), 0), func.count(Sale.id))
        .where(*in_range)
    ).one()

    cost = db.session.scalar(
        db.select(func.coalesce(func.sum(SaleItem.unit_cost * SaleItem.quantity), 0))
        .select_from(SaleItem)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .where(*in_range)
    )

    revenue, cost = money(revenue), money(cost)
    return {"revenue": revenue, "cost": cost, "profit": revenue - cost, "orders": orders}


# ---------- the page ----------

@analytics.route("/")
@roles_required(*MANAGERS)
def overview():
    days = request.args.get("days", 30, type=int)
    if days not in RANGES:           # whitelist: never trust the query string
        days = 30

    today = datetime.now(shop_tz()).date()
    first_day = today - timedelta(days=days - 1)
    start = day_start_utc(first_day)
    end = day_start_utc(today + timedelta(days=1))
    prev_start = day_start_utc(first_day - timedelta(days=days))

    current = period_totals(start, end)
    previous = period_totals(prev_start, start)    # the period right before it

    current["avg_order"] = (current["revenue"] / current["orders"]).quantize(CENT) \
        if current["orders"] else Decimal("0.00")
    current["margin"] = (current["profit"] / current["revenue"] * 100).quantize(Decimal("0.1")) \
        if current["revenue"] else Decimal("0.0")

    change = None
    if previous["revenue"] > 0:
        change = ((current["revenue"] - previous["revenue"])
                  / previous["revenue"] * 100).quantize(Decimal("0.1"))

    # --- daily series, bucketed by the shop's local date ---
    cost_per_sale = (
        db.select(SaleItem.sale_id,
                  func.sum(SaleItem.unit_cost * SaleItem.quantity).label("cost"))
        .group_by(SaleItem.sale_id)
        .subquery()
    )
    rows = db.session.execute(
        db.select(Sale.created_at, Sale.total, func.coalesce(cost_per_sale.c.cost, 0))
        .outerjoin(cost_per_sale, cost_per_sale.c.sale_id == Sale.id)
        .where(Sale.created_at >= start, Sale.created_at < end)
    )

    daily = {first_day + timedelta(days=i): [Decimal("0"), Decimal("0")]
             for i in range(days)}                       # zero-filled: no gaps in the chart
    for created_at, total, cost in rows:
        bucket = daily.get(to_local_date(created_at))
        if bucket is not None:
            bucket[0] += money(total)
            bucket[1] += money(total) - money(cost)

    chart = {                                            # floats are for display only
        "labels": [d.strftime("%d %b") for d in daily],
        "revenue": [float(v[0]) for v in daily.values()],
        "profit": [float(v[1]) for v in daily.values()],
    }

    # --- top products: GROUP BY product ---
    revenue_expr = func.sum(SaleItem.unit_price * SaleItem.quantity)
    top_rows = db.session.execute(
        db.select(
            Product.name, Product.sku,
            func.sum(SaleItem.quantity).label("units"),
            revenue_expr.label("revenue"),
            func.sum((SaleItem.unit_price - SaleItem.unit_cost) * SaleItem.quantity).label("profit"),
        )
        .select_from(SaleItem)
        .join(Product, SaleItem.product_id == Product.id)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .where(Sale.created_at >= start, Sale.created_at < end)
        .group_by(Product.id, Product.name, Product.sku)
        .order_by(revenue_expr.desc())
        .limit(10)
    ).all()
    top_products = [{"name": r.name, "sku": r.sku, "units": r.units,
                     "revenue": money(r.revenue), "profit": money(r.profit)}
                    for r in top_rows]

    # --- sales by cashier: GROUP BY user ---
    cashier_rows = db.session.execute(
        db.select(User.name, func.count(Sale.id).label("orders"),
                  func.sum(Sale.total).label("revenue"))
        .select_from(Sale)
        .join(User, Sale.user_id == User.id)
        .where(Sale.created_at >= start, Sale.created_at < end)
        .group_by(User.id, User.name)
        .order_by(func.sum(Sale.total).desc())
    ).all()
    by_cashier = [{"name": r.name, "orders": r.orders, "revenue": money(r.revenue)}
                  for r in cashier_rows]

    return render_template("analytics/overview.html", days=days, ranges=RANGES,
                           current=current, change=change, chart=chart,
                           top_products=top_products, by_cashier=by_cashier)