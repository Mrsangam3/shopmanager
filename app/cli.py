import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import click

from app.extensions import db
from app.models import User, Role, Category, Product, Sale, SaleItem


def register_cli(app):
    @app.cli.command("create-owner")
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_owner(name, email, password):
        """Create an owner account."""
        email = email.strip().lower()
        if db.session.scalar(db.select(User).filter_by(email=email)):
            click.echo("A user with that email already exists.")
            return
        user = User(name=name.strip(), email=email, role=Role.OWNER)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Owner {email} created.")
    @app.cli.command("seed-sales")
    @click.option("--days", default=60, show_default=True)
    @click.option("--per-day", default=6, show_default=True)
    def seed_sales(days, per_day):
        """Create fake past sales to test analytics. Does NOT change stock."""
        users = db.session.scalars(db.select(User)).all()
        products = db.session.scalars(
            db.select(Product).where(Product.is_active.is_(True))).all()
        if not users or not products:
            click.echo("You need at least one user and one product first.")
            return

        rng = random.Random(42)
        now = datetime.now(timezone.utc)
        count = 0
        for d in range(days):
            for _ in range(rng.randint(max(per_day - 3, 0), per_day + 3)):
                when = now - timedelta(days=d, hours=rng.randint(0, 11),
                                       minutes=rng.randint(0, 59))
                sale = Sale(user_id=rng.choice(users).id, total=Decimal("0.00"),
                            customer_name="Demo data", created_at=when)
                total = Decimal("0.00")
                for p in rng.sample(products, k=min(rng.randint(1, 3), len(products))):
                    qty = rng.randint(1, 4)
                    sale.items.append(SaleItem(product_id=p.id, quantity=qty,
                                               unit_price=p.price, unit_cost=p.cost))
                    total += p.price * qty
                sale.total = total
                db.session.add(sale)
                count += 1
        db.session.commit()
        click.echo(f"Created {count} demo sales over {days} days.")

    @app.cli.command("clear-demo-sales")
    def clear_demo_sales():
        """Remove everything created by seed-sales."""
        demo = db.session.scalars(
            db.select(Sale).where(Sale.customer_name == "Demo data")).all()
        for sale in demo:
            db.session.delete(sale)      # ORM delete cascades to the sale's items
        db.session.commit()
        click.echo(f"Removed {len(demo)} demo sales.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Add sample categories and products for testing."""
        if db.session.scalar(db.select(db.func.count(Product.id))):
            click.echo("Products already exist; skipping.")
            return
        cats = [Category(name=n) for n in ("Groceries", "Beverages", "Stationery")]
        db.session.add_all(cats)
        for i in range(1, 26):
            price = Decimal(10 + i * 3)
            db.session.add(Product(
                name=f"Sample Item {i}", sku=f"SKU-{i:03d}",
                category=cats[i % 3], price=price,
                cost=(price * Decimal("0.7")).quantize(Decimal("0.01")),
                quantity=(i * 7) % 40, reorder_level=10,
            ))
        db.session.commit()
        click.echo("Added 3 categories and 25 products.")