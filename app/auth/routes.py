from urllib.parse import urlsplit

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db, limiter
from app.models import User, Role
from app.decorators import roles_required

auth = Blueprint("auth", __name__, url_prefix="/auth")


def is_safe_next(target):
    """Only allow relative paths on our own site (prevents open redirects)."""
    if not target or "\\" in target or target.startswith("//"):
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc and target.startswith("/")


@auth.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"],
               deduct_when=lambda response: response.status_code == 401)  # count failures only
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = db.session.scalar(db.select(User).filter_by(email=email))

        if user is None or not user.check_password(password):
            # same message for both cases: don't reveal which emails exist
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html"), 401

        login_user(user)
        next_url = request.args.get("next")
        return redirect(next_url if is_safe_next(next_url) else url_for("main.dashboard"))

    return render_template("auth/login.html")


@auth.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth.route("/employees", methods=["GET", "POST"])
@roles_required(Role.OWNER)
def employees():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "")
        password = request.form.get("password", "")

        error = None
        if not name or not email:
            error = "Name and email are required."
        elif role not in (Role.MANAGER, Role.CASHIER):   # never trust the form
            error = "Invalid role."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        elif db.session.scalar(db.select(User).filter_by(email=email)):
            error = "That email is already registered."

        if error:
            flash(error, "danger")
        else:
            user = User(name=name, email=email, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f"{name} added as {role}.", "success")
            return redirect(url_for("auth.employees"))

    users = db.session.scalars(db.select(User).order_by(User.name)).all()
    return render_template("auth/employees.html", users=users,
                           roles=(Role.MANAGER, Role.CASHIER))