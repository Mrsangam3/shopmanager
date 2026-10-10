from decimal import Decimal

from app.extensions import db
from app.models import Product, Sale, SaleItem

MAX_TOTAL = Decimal("99999999.99")   # fits Numeric(10, 2)


class SaleError(Exception):
    """A sale that can't be completed. The message is safe to show the user."""


def create_sale(user, lines, customer_name=None):
    """Create a sale atomically.

    `lines` maps product_id -> quantity. Either every item is sold and the
    stock is deducted, or nothing at all changes.
    """
    try:
        ids = sorted(lines)   # fixed order, so two sales can't deadlock each other
        products = {
            p.id: p for p in db.session.scalars(
                db.select(Product).where(Product.id.in_(ids),
                                         Product.is_active.is_(True)))
        }

        sale = Sale(user_id=user.id, customer_name=customer_name or None,
                    total=Decimal("0.00"))
        total = Decimal("0.00")

        for pid in ids:
            qty = lines[pid]
            product = products.get(pid)
            if product is None:
                raise SaleError("One of the products is no longer available.")

            # Atomic check-and-deduct: only succeeds if enough stock remains.
            result = db.session.execute(
                db.update(Product)
                .where(Product.id == pid, Product.quantity >= qty)
                .values(quantity=Product.quantity - qty)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise SaleError(f"Not enough stock for {product.name}.")

            # Price and cost both come from the database, never from the browser.
            sale.items.append(SaleItem(product_id=pid, quantity=qty,
                                       unit_price=product.price,
                                       unit_cost=product.cost))
            total += product.price * qty

        if total > MAX_TOTAL:
            raise SaleError("This sale total is too large.")

        sale.total = total
        db.session.add(sale)
        db.session.commit()      # all changes become permanent together
        return sale
    except Exception:
        db.session.rollback()    # any failure undoes everything above
        raise