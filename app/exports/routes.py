import csv
from datetime import date, datetime, timedelta, timezone
from io import StringIO

from flask import (Blueprint, Response, flash, redirect, render_template,
                   request, stream_with_context, url_for)

from app.analytics.routes import day_start_utc, shop_tz
from app.decorators import roles_required
from app.extensions import db
from app.models import (Category, Product, Purchase, PurchaseItem, Role, Sale,
                        SaleItem, Supplier, User)

exports = Blueprint("exports", __name__, url_prefix="/exports")

MANAGERS = (Role.OWNER, Role.MANAGER)
MAX_DAYS = 366     # longest date range one export may cover
BATCH = 500        # rows fetched from the database at a time
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


class ExportError(Exception):
    """A bad export request. The message is safe to show the user."""


# ---------- helpers ----------

def safe(value):
    """Text for a CSV cell. Neutralises spreadsheet formulas (CSV injection)."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(FORMULA_STARTS):
        return "'" + text
    return text


def money(value):
    """Exact 2-decimal string. Numbers are formatted by us, so never sanitised."""
    return "{:.2f}".format(value or 0)


def local_dt(dt):
    """Stored times are UTC; export them in the shop's time zone."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(shop_tz()).strftime("%Y-%m-%d %H:%M")


def csv_response(filename, header, rows):
    """Stream a CSV download. `rows` is a generator, so memory use stays flat."""
    def generate():
        buffer = StringIO()
        writer = csv.writer(buffer)
        yield "\ufeff"                      # BOM, so Excel reads UTF-8 correctly
        writer.writerow(header)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for row in rows:
            writer.writerow(row)
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    response = Response(stream_with_context(generate()), mimetype="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = "no-store"
    return response


def read_range():
    """Validate ?from=YYYY-MM-DD&to=YYYY-MM-DD.
    Returns (first_day, last_day, start_utc, end_utc) with a half-open range."""
    try:
        first_day = date.fromisoformat(request.args.get("from", ""))
        last_day = date.fromisoformat(request.args.get("to", ""))
    except ValueError:
        raise ExportError("Choose a valid start date and end date.")
    if last_day < first_day:
        raise ExportError("The end date can't be before the start date.")
    if (last_day - first_day).days + 1 > MAX_DAYS:
        raise ExportError(f"Choose a range of at most {MAX_DAYS} days.")
    return (first_day, last_day,
            day_start_utc(first_day), day_start_utc(last_day + timedelta(days=1)))


# ---------- routes ----------

@exports.route("/")
@roles_required(*MANAGERS)
def index():
    today = datetime.now(shop_tz()).date()
    return render_template("exports/index.html",
                           today=today.isoformat(),
                           default_from=(today - timedelta(days=29)).isoformat())


@exports.route("/inventory.csv")
@roles_required(*MANAGERS)
def inventory_csv():
    today = datetime.now(shop_tz()).date()
    header = ["SKU", "Name", "Category", "Price", "Cost", "Quantity",
              "Reorder level", "Low stock", "Status"]

    def rows():
        stmt = (db.select(Product.sku, Product.name, Category.name,
                          Product.price, Product.cost, Product.quantity,
                          Product.reorder_level, Product.is_active)
                .outerjoin(Category, Product.category_id == Category.id)
                .order_by(Product.name)
                .execution_options(yield_per=BATCH))
        for sku, name, category, price, cost, qty, reorder, active in db.session.execute(stmt):
            yield [safe(sku), safe(name), safe(category), money(price), money(cost),
                   qty, reorder, "Yes" if qty <= reorder else "No",
                   "Active" if active else "Archived"]

    return csv_response(f"inventory_{today}.csv", header, rows())


@exports.route("/sales.csv")
@roles_required(*MANAGERS)
def sales_csv():
    try:
        first_day, last_day, start, end = read_range()
    except ExportError as e:
        flash(str(e), "danger")
        return redirect(url_for("exports.index"))

    header = ["Invoice", "Date", "Cashier", "Customer", "SKU", "Product",
              "Quantity", "Unit price", "Unit cost", "Line total", "Line profit"]

    def rows():
        stmt = (db.select(Sale.id, Sale.created_at, User.name, Sale.customer_name,
                          Product.sku, Product.name, SaleItem.quantity,
                          SaleItem.unit_price, SaleItem.unit_cost)
                .select_from(SaleItem)
                .join(Sale, SaleItem.sale_id == Sale.id)
                .join(User, Sale.user_id == User.id)
                .join(Product, SaleItem.product_id == Product.id)
                .where(Sale.created_at >= start, Sale.created_at < end)
                .order_by(Sale.created_at, Sale.id, SaleItem.id)
                .execution_options(yield_per=BATCH))
        for sale_id, created, cashier, customer, sku, product, qty, price, cost in db.session.execute(stmt):
            yield [f"INV-{sale_id:06d}", local_dt(created), safe(cashier),
                   safe(customer), safe(sku), safe(product), qty,
                   money(price), money(cost),
                   money(price * qty), money((price - cost) * qty)]

    return csv_response(f"sales_{first_day}_to_{last_day}.csv", header, rows())


@exports.route("/purchases.csv")
@roles_required(*MANAGERS)
def purchases_csv():
    try:
        first_day, last_day, start, end = read_range()
    except ExportError as e:
        flash(str(e), "danger")
        return redirect(url_for("exports.index"))

    header = ["Reference", "Date", "Supplier", "Recorded by", "SKU", "Product",
              "Quantity", "Unit cost", "Line total"]

    def rows():
        stmt = (db.select(Purchase.id, Purchase.created_at, Supplier.name, User.name,
                          Product.sku, Product.name, PurchaseItem.quantity,
                          PurchaseItem.unit_cost)
                .select_from(PurchaseItem)
                .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
                .join(Supplier, Purchase.supplier_id == Supplier.id)
                .join(User, Purchase.user_id == User.id)
                .join(Product, PurchaseItem.product_id == Product.id)
                .where(Purchase.created_at >= start, Purchase.created_at < end)
                .order_by(Purchase.created_at, Purchase.id, PurchaseItem.id)
                .execution_options(yield_per=BATCH))
        for purchase_id, created, supplier, user, sku, product, qty, cost in db.session.execute(stmt):
            yield [f"PUR-{purchase_id:06d}", local_dt(created), safe(supplier),
                   safe(user), safe(sku), safe(product), qty,
                   money(cost), money(cost * qty)]

    return csv_response(f"purchases_{first_day}_to_{last_day}.csv", header, rows())