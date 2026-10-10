from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Product, Sale, SaleItem, Role
from app.sales.services import create_sale, SaleError

sales = Blueprint("sales", __name__, url_prefix="/sales")

MANAGERS = (Role.OWNER, Role.MANAGER)
MAX_LINES = 100
MAX_QTY = 10_000


def read_lines(form):
    """Turn the submitted cart into {product_id: quantity}, or raise SaleError."""
    ids = form.getlist("product_id")
    qtys = form.getlist("quantity")
    if len(ids) != len(qtys):
        raise SaleError("The cart was malformed. Please try again.")
    if not ids:
        raise SaleError("Add at least one item to the sale.")
    if len(ids) > MAX_LINES:
        raise SaleError(f"A sale can have at most {MAX_LINES} lines.")

    lines = {}
    for raw_id, raw_qty in zip(ids, qtys):
        try:
            pid, qty = int(raw_id), int(raw_qty)
        except ValueError:
            raise SaleError("The cart was malformed. Please try again.")
        if qty < 1 or qty > MAX_QTY:
            raise SaleError(f"Quantities must be between 1 and {MAX_QTY:,}.")
        lines[pid] = lines.get(pid, 0) + qty   # merge duplicate products
    return lines


@sales.route("/new", methods=["GET", "POST"])
@login_required
def new_sale():
    lines = {}
    customer = ""
    if request.method == "POST":
        customer = request.form.get("customer_name", "").strip()[:120]
        try:
            lines = read_lines(request.form)
            sale = create_sale(current_user, lines, customer)
        except SaleError as e:
            flash(str(e), "danger")      # fall through and re-render with the cart kept
        else:
            flash("Sale completed.", "success")
            now_low = db.session.scalars(
                db.select(Product).where(Product.id.in_(list(lines)),
                Product.is_low_stock)).all()
            if now_low:
                flash("Low stock: " + ", ".join(p.name for p in now_low), "warning")
            return redirect(url_for("sales.invoice", sale_id=sale.id))

    products = db.session.scalars(
        db.select(Product)
        .where(Product.is_active.is_(True), Product.quantity > 0)
        .order_by(Product.name)
    ).all()
    payload = [{"id": p.id, "sku": p.sku, "name": p.name,
                "price": str(p.price), "stock": p.quantity} for p in products]
    prefill = [{"id": pid, "qty": qty} for pid, qty in lines.items()]

    return render_template("sales/new.html", products=payload,
                           prefill=prefill, customer=customer)


@sales.route("/")
@login_required
def history():
    page = request.args.get("page", 1, type=int)
    stmt = (db.select(Sale)
            .options(joinedload(Sale.user))
            .order_by(Sale.created_at.desc(), Sale.id.desc()))
    if not current_user.has_role(*MANAGERS):          # cashiers see only their own
        stmt = stmt.where(Sale.user_id == current_user.id)
    pagination = db.paginate(stmt, page=page, per_page=15, error_out=False)
    return render_template("sales/history.html", pagination=pagination)


@sales.route("/<int:sale_id>")
@login_required
def invoice(sale_id):
    sale = db.get_or_404(
        Sale, sale_id,
        options=[selectinload(Sale.items).joinedload(SaleItem.product),
                 joinedload(Sale.user)])
    if sale.user_id != current_user.id and not current_user.has_role(*MANAGERS):
        abort(403)
    return render_template("sales/invoice.html", sale=sale)