from sqlalchemy import inspect, text

from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    print("Database:", db.engine.url)
    inspector = inspect(db.engine)

    sale_item_columns = [c["name"] for c in inspector.get_columns("sale_items")]
    sales_indexes = [i["name"] for i in inspector.get_indexes("sales")]

    with db.engine.begin() as conn:
        if "unit_cost" in sale_item_columns:
            print("sale_items.unit_cost already exists - nothing to add.")
        else:
            conn.execute(text(
                "ALTER TABLE sale_items "
                "ADD COLUMN unit_cost NUMERIC(10, 2) NOT NULL DEFAULT 0"
            ))
            # old sales get each product's current cost (an approximation)
            conn.execute(text(
                "UPDATE sale_items SET unit_cost = "
                "(SELECT cost FROM products WHERE products.id = sale_items.product_id)"
            ))
            print("Added sale_items.unit_cost and backfilled old sales.")

        if "ix_sales_created_at" in sales_indexes:
            print("Index ix_sales_created_at already exists - nothing to add.")
        else:
            conn.execute(text(
                "CREATE INDEX ix_sales_created_at ON sales (created_at)"
            ))
            print("Added index ix_sales_created_at.")

    print("Done.")