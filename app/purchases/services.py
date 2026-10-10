from decimal import Decimal, ROUND_HALF_UP

from app.extensions import db
from app.models import Product, Supplier, Purchase, PurchaseItem

CENT = Decimal("0.01")
MAX_TOTAL = Decimal("99999999.99")   # fits Numeric(10, 2)


class PurchaseError(Exception):
    """A purchase that can't be recorded. The message is safe to show the user."""


def create_purchase(user, supplier_id, lines):
    """Record a delivery atomically.

    `lines` is a list of {"product_id", "quantity", "unit_cost"} dicts.
    Stock and weighted-average cost are updated together with the purchase record.
    """
    try:
        supplier = db.session.get(Supplier, supplier_id)
        if supplier is None:
            raise PurchaseError("Choose a valid supplier.")

        ids = sorted({line["product_id"] for line in lines})
        products = {
            p.id: p for p in db.session.scalars(
                db.select(Product)
                .where(Product.id.in_(ids), Product.is_active.is_(True))
                .order_by(Product.id)          # fixed lock order avoids deadlocks
                .with_for_update())            # row locks held until commit/rollback
        }

        purchase = Purchase(supplier_id=supplier.id, user_id=user.id,
                            total=Decimal("0.00"))
        total = Decimal("0.00")

        for line in lines:
            product = products.get(line["product_id"])
            if product is None:
                raise PurchaseError("One of the products is no longer available.")

            qty, unit_cost = line["quantity"], line["unit_cost"]
            new_qty = product.quantity + qty
            product.cost = (
                (product.quantity * product.cost + qty * unit_cost) / new_qty
            ).quantize(CENT, rounding=ROUND_HALF_UP)
            product.quantity = new_qty

            purchase.items.append(PurchaseItem(product_id=product.id,
                                               quantity=qty, unit_cost=unit_cost))
            total += unit_cost * qty

        if total > MAX_TOTAL:
            raise PurchaseError("This purchase total is too large.")

        purchase.total = total
        db.session.add(purchase)
        db.session.commit()
        return purchase
    except Exception:
        db.session.rollback()
        raise