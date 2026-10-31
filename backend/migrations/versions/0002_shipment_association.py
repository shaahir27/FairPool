"""Require captured shipment orders to belong to the funded lot.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM shipments s JOIN buyer_orders b ON b.id=s.buyer_order_id
               WHERE b.lot_id <> s.lot_id) THEN
        RAISE EXCEPTION 'Existing cross-lot shipments require operator review' USING ERRCODE='23514';
    END IF;
    END $$""")
    op.execute("DROP TRIGGER trg_shipments_funded_only ON shipments")
    op.execute("""CREATE TRIGGER trg_shipments_funded_only
        BEFORE INSERT OR UPDATE OF lot_id, buyer_order_id ON shipments
        FOR EACH ROW EXECUTE FUNCTION fn_shipments_funded_only()""")
    op.execute(
        "CREATE OR REPLACE FUNCTION fn_shipments_funded_only() RETURNS trigger\nLANGUAGE plpgsql AS $$\nBEGIN\n    IF NOT EXISTS (\n        SELECT 1 FROM lots l\n        JOIN buyer_orders bo ON bo.id = NEW.buyer_order_id\n        WHERE l.id = NEW.lot_id AND bo.lot_id = l.id\n          AND l.status IN ('FUNDED'::lot_status, 'CLOSED'::lot_status)\n          AND bo.status = 'CAPTURED'::buyer_order_status\n    ) THEN\n        RAISE EXCEPTION 'shipments require a funded lot and a captured order'\n            USING ERRCODE = '23514';\n    END IF;\n    RETURN NEW;\nEND;\n$$"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_shipments_funded_only ON shipments")
    op.execute("""CREATE TRIGGER trg_shipments_funded_only BEFORE INSERT ON shipments
        FOR EACH ROW EXECUTE FUNCTION fn_shipments_funded_only()""")
    op.execute(
        "CREATE OR REPLACE FUNCTION fn_shipments_funded_only() RETURNS trigger\nLANGUAGE plpgsql AS $$\nBEGIN\n    IF NOT EXISTS (\n        SELECT 1 FROM lots l\n        JOIN buyer_orders bo ON bo.id = NEW.buyer_order_id\n        WHERE l.id = NEW.lot_id\n          AND l.status IN ('FUNDED'::lot_status, 'CLOSED'::lot_status)\n          AND bo.status = 'CAPTURED'::buyer_order_status\n    ) THEN\n        RAISE EXCEPTION 'shipments require a funded lot and a captured order'\n            USING ERRCODE = '23514';\n    END IF;\n    RETURN NEW;\nEND;\n$$"
    )
