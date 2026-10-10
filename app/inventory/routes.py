from decimal import Decimal, InvalidOperation

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from sqlalchemy import or_, func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Product, Category, Supplier, Purchase, PurchaseItem, Role
from app.decorators import roles_required

inventory = Blueprint("inventory", __name__, url_prefix="/inventory")

MANAGERS = (Role.OWNER, Role.MANAGER)
PER_PAGE = 10
MAX_MONEY = Decimal("99999999.99")   # fits Numeric(10, 2)


# ---------- helpers ----------

def parse_money(raw, label):
    try:
        amount = Decimal((raw or "").strip()).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"{label} must be a valid amount.")
    if amount < 0 or amount > MAX_MONEY:
        raise ValueError(f"{label} is out of range.")
    return amount


def parse_count(raw, label):
    try:
        number = int((raw or "").strip())
    except ValueError:
        raise ValueError(f"{label} must be a whole number.")
    if number < 0 or number > 1_000_000:
        raise ValueError(f"{label} is out of range.")
    return number


def read_product_form(form, current_id=None):
    """Validate the submitted form. Returns (clean_data, list_of_errors)."""
    errors = []
    name = form.get("name", "").strip()
    sku = form.get("sku", "").strip().upper()

    if not name:
        errors.append("Name is required.")
    if not sku:
        errors.append("SKU is required.")
    else:
        existing = db.session.scalar(db.select(Product).filter_by(sku=sku))
        if existing and existing.id != current_id:
            errors.append(f"SKU {sku} is already used by another product.")

    values = {}
    for field, label in (("price", "Price"), ("cost", "Cost")):
        try:
            values[field] = parse_money(form.get(field), label)
        except ValueError as e:
            errors.append(str(e))
    for field, label in (("quantity", "Quantity"), ("reorder_level", "Reorder level")):
        try:
            values[field] = parse_count(form.get(field), label)
        except ValueError as e:
            errors.append(str(e))

    category_id = form.get("category_id") or None
    if category_id:
        if not category_id.isdigit() or db.session.get(Category, int(category_id)) is None:
            errors.append("Invalid category.")
        else:
            category_id = int(category_id)

    return dict(name=name, sku=sku, category_id=category_id, **values), errors


def product_to_values(p):
    return {"name": p.name, "sku": p.sku, "category_id": p.category_id or "",
            "price": p.price, "cost": p.cost,
            "quantity": p.quantity, "reorder_level": p.reorder_level}


def all_categories():
    return db.session.scalars(db.select(Category).order_by(Category.name)).all()


# ---------- products ----------

@inventory.route("/")
@login_required
def products():
    page = request.args.get("page", 1, type=int)
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    low = request.args.get("low") == "1"
    can_manage = current_user.has_role(*MANAGERS)
    archived = can_manage and request.args.get("archived") == "1"

    stmt = (db.select(Product)
            .options(joinedload(Product.category))      # avoids the N+1 problem
            .where(Product.is_active == (not archived)))

    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Product.name.ilike(like), Product.sku.ilike(like)))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if low:
        stmt = stmt.where(Product.is_low_stock)

    stmt = stmt.order_by(Product.name)
    pagination = db.paginate(stmt, page=page, per_page=PER_PAGE, error_out=False)

    return render_template("inventory/products.html", pagination=pagination,
                           categories=all_categories(), q=q, category_id=category_id,
                           low=low, archived=archived, can_manage=can_manage)


@inventory.route("/products/new", methods=["GET", "POST"])
@roles_required(*MANAGERS)
def new_product():
    values = {}
    if request.method == "POST":
        data, errors = read_product_form(request.form)
        if errors:
            for e in errors:
                flash(e, "danger")
            values = request.form
        else:
            db.session.add(Product(**data))
            db.session.commit()
            flash(f"{data['name']} added.", "success")
            return redirect(url_for("inventory.products"))
    return render_template("inventory/product_form.html", product=None,
                           values=values, categories=all_categories())


@inventory.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@roles_required(*MANAGERS)
def edit_product(product_id):
    product = db.get_or_404(Product, product_id)
    values = product_to_values(product)
    if request.method == "POST":
        data, errors = read_product_form(request.form, current_id=product.id)
        if errors:
            for e in errors:
                flash(e, "danger")
            values = request.form
        else:
            for key, val in data.items():
                setattr(product, key, val)
            db.session.commit()
            flash("Product updated.", "success")
            return redirect(url_for("inventory.products"))
    return render_template("inventory/product_form.html", product=product,
                           values=values, categories=all_categories())


@inventory.route("/products/<int:product_id>/toggle", methods=["POST"])
@roles_required(*MANAGERS)
def toggle_product(product_id):
    product = db.get_or_404(Product, product_id)
    product.is_active = not product.is_active
    db.session.commit()
    state = "restored" if product.is_active else "archived"
    flash(f"{product.name} {state}.", "info")
    return redirect(url_for("inventory.products"))


# ---------- categories ----------

@inventory.route("/categories", methods=["GET", "POST"])
@roles_required(*MANAGERS)
def categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Category name is required.", "danger")
        elif db.session.scalar(db.select(Category)
                               .where(func.lower(Category.name) == name.lower())):
            flash("That category already exists.", "danger")
        else:
            db.session.add(Category(name=name))
            db.session.commit()
            flash(f"Category '{name}' added.", "success")
            return redirect(url_for("inventory.categories"))
    return render_template("inventory/categories.html", categories=all_categories())

@inventory.route("/reorder")
@roles_required(*MANAGERS)
def reorder():
    products = db.session.scalars(
        db.select(Product)
        .options(joinedload(Product.category))
        .where(Product.is_active.is_(True), Product.is_low_stock)
        .order_by(Product.quantity, Product.name)
    ).all()

    # Most recent supplier for each low product, from purchase history
    last_supplier = {}
    if products:
        rows = db.session.execute(
            db.select(PurchaseItem.product_id, Supplier)
            .join(Purchase, PurchaseItem.purchase_id == Purchase.id)
            .join(Supplier, Purchase.supplier_id == Supplier.id)
            .where(PurchaseItem.product_id.in_([p.id for p in products]))
            .order_by(Purchase.created_at.desc(), Purchase.id.desc())
        )
        for product_id, supplier in rows:
            last_supplier.setdefault(product_id, supplier)   # first row seen = newest

    groups = {}
    for p in products:
        groups.setdefault(last_supplier.get(p.id), []).append({
            "product": p,
            # order back up to twice the reorder level (never less than 1)
            "suggested": max(p.reorder_level * 2 - p.quantity, 1),
        })

    # alphabetical by supplier, "no supplier on record" last
    ordered = sorted(groups.items(),
                     key=lambda kv: (kv[0] is None, kv[0].name if kv[0] else ""))

    return render_template("inventory/reorder.html", groups=ordered,
                           total=len(products))


@inventory.route("/categories/<int:category_id>/delete", methods=["POST"])
@roles_required(*MANAGERS)
def delete_category(category_id):
    category = db.get_or_404(Category, category_id)
    if category.products:
        flash(f"Can't delete '{category.name}': it still has products.", "danger")
    else:
        db.session.delete(category)
        db.session.commit()
        flash("Category deleted.", "info")
    return redirect(url_for("inventory.categories"))