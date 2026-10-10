from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Product, Role

main = Blueprint("main", __name__)


@main.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main.route("/dashboard")
@login_required
def dashboard():
    active = Product.is_active.is_(True)
    low = Product.is_low_stock

    total_products = db.session.scalar(
        db.select(func.count(Product.id)).where(active))
    low_count = db.session.scalar(
        db.select(func.count(Product.id)).where(active, low))
    out_of_stock = db.session.scalar(
        db.select(func.count(Product.id)).where(active, Product.quantity == 0))
    stock_value = db.session.scalar(
        db.select(func.coalesce(func.sum(Product.cost * Product.quantity), 0))
        .where(active))

    low_items = db.session.scalars(
        db.select(Product)
        .options(joinedload(Product.category))
        .where(active, low)
        .order_by(Product.quantity, Product.name)
        .limit(8)
    ).all()

    return render_template(
        "dashboard.html",
        total_products=total_products,
        low_count=low_count,
        out_of_stock=out_of_stock,
        stock_value=stock_value,
        low_items=low_items,
        can_see_costs=current_user.has_role(Role.OWNER, Role.MANAGER),
    )