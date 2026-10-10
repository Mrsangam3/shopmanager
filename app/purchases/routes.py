from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import current_user
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import Product, Supplier, Purchase, PurchaseItem, Role
from app.decorators import roles_required
from app.purchases.services import create_purchase, PurchaseError, CENT, MAX_TOTAL

purchases = Blueprint("purchases", __name__, url_prefix="/purchases")

MANAGERS = (Role.OWNER, Role.MANAGER)
MAX_LINES = 100
MAX_QTY = 100_000


def read_lines(form):
    ids = form.getlist("product_id")
    qtys = form.getlist("quantity")
    costs = form.getlist("unit_cost")
    if not (len(ids) == len(qtys) == len(costs)):
        raise PurchaseError("The form was malformed. Please try again.")
    if not ids:
        raise PurchaseError("Add at least one item to the purchase.")
    if len(ids) > MAX_LINES:
        raise PurchaseError(f"A purchase can have at most {MAX_LINES} lines.")

    lines = []
    for raw_id, raw_qty, raw_cost in zip(ids, qtys, costs):
        try:
            pid = int(raw_id)
            qty = int(raw_qty)
            cost = Decimal(raw_cost.strip()).quantize(CENT)
        except (ValueError, InvalidOperation):
            raise PurchaseError("Quantities and costs must be valid numbers.")
        if qty < 1 or qty > MAX_QTY:
            raise PurchaseError(f"Quantities must be between 1 and {MAX_QTY:,}.")
        if cost < 0 or cost > MAX_TOTAL:
            raise PurchaseError("A unit cost is out of range.")
        lines.append({"product_id": pid, "quantity": qty, "unit_cost": cost})
    return lines


def all_suppliers():
    return db.session.scalars(db.select(Supplier).order_by(Supplier.name)).all()


# ---------- purchases ----------

@purchases.route("/new", methods=["GET", "POST"])
@roles_required(*MANAGERS)
def new_purchase():
    suppliers = all_suppliers()
    if not suppliers:
        flash("Add a supplier before recording a purchase.", "warning")
        return redirect(url_for("purchases.new_supplier"))

    prefill = []
    selected_supplier = None
    if request.method == "POST":
        selected_supplier = request.form.get("supplier_id", type=int)
        prefill = [{"id": i, "qty": q, "cost": c} for i, q, c in zip(
            request.form.getlist("product_id"),
            request.form.getlist("quantity"),
            request.form.getlist("unit_cost"))]
        try:
            lines = read_lines(request.form)
            if selected_supplier is None:
                raise PurchaseError("Choose a supplier.")
            purchase = create_purchase(current_user, selected_supplier, lines)
        except PurchaseError as e:
            flash(str(e), "danger")      # fall through and re-render with the cart kept
        else:
            flash("Purchase recorded and stock updated.", "success")
            return redirect(url_for("purchases.detail", purchase_id=purchase.id))

    products = db.session.scalars(
        db.select(Product).where(Product.is_active.is_(True)).order_by(Product.name)
    ).all()
    payload = [{"id": p.id, "sku": p.sku, "name": p.name,
                "cost": str(p.cost), "stock": p.quantity} for p in products]

    return render_template("purchases/new.html", suppliers=suppliers,
                           products=payload, prefill=prefill,
                           selected_supplier=selected_supplier)


@purchases.route("/")
@roles_required(*MANAGERS)
def history():
    page = request.args.get("page", 1, type=int)
    stmt = (db.select(Purchase)
            .options(joinedload(Purchase.supplier), joinedload(Purchase.user))
            .order_by(Purchase.created_at.desc(), Purchase.id.desc()))
    pagination = db.paginate(stmt, page=page, per_page=15, error_out=False)
    return render_template("purchases/history.html", pagination=pagination)


@purchases.route("/<int:purchase_id>")
@roles_required(*MANAGERS)
def detail(purchase_id):
    purchase = db.get_or_404(
        Purchase, purchase_id,
        options=[selectinload(Purchase.items).joinedload(PurchaseItem.product),
                 joinedload(Purchase.supplier), joinedload(Purchase.user)])
    return render_template("purchases/detail.html", purchase=purchase)


# ---------- suppliers ----------

def read_supplier_form(form):
    name = form.get("name", "").strip()
    phone = form.get("phone", "").strip()
    email = form.get("email", "").strip()
    errors = []
    if not name:
        errors.append("Supplier name is required.")
    if len(name) > 120 or len(email) > 120 or len(phone) > 30:
        errors.append("One of the fields is too long.")
    return {"name": name, "phone": phone or None, "email": email or None}, errors


@purchases.route("/suppliers")
@roles_required(*MANAGERS)
def suppliers():
    return render_template("purchases/suppliers.html", suppliers=all_suppliers())


@purchases.route("/suppliers/new", methods=["GET", "POST"])
@roles_required(*MANAGERS)
def new_supplier():
    values = {}
    if request.method == "POST":
        data, errors = read_supplier_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            values = request.form
        else:
            db.session.add(Supplier(**data))
            db.session.commit()
            flash(f"Supplier {data['name']} added.", "success")
            return redirect(url_for("purchases.suppliers"))
    return render_template("purchases/supplier_form.html", supplier=None, values=values)


@purchases.route("/suppliers/<int:supplier_id>/edit", methods=["GET", "POST"])
@roles_required(*MANAGERS)
def edit_supplier(supplier_id):
    supplier = db.get_or_404(Supplier, supplier_id)
    values = {"name": supplier.name, "phone": supplier.phone or "",
              "email": supplier.email or ""}
    if request.method == "POST":
        data, errors = read_supplier_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            values = request.form
        else:
            for key, val in data.items():
                setattr(supplier, key, val)
            db.session.commit()
            flash("Supplier updated.", "success")
            return redirect(url_for("purchases.suppliers"))
    return render_template("purchases/supplier_form.html", supplier=supplier, values=values)