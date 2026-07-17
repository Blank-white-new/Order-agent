"""enforce phase 2 tenant and version integrity

Revision ID: 20260717_0003
Revises: 20260716_0002
Create Date: 2026-07-17 12:00:00+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260717_0003"
down_revision = "20260716_0002"
branch_labels = None
depends_on = None


def _assert_no_existing_conflicts() -> None:
    bind = op.get_bind()
    checks = {
        "duplicate conversation session_key": """
            SELECT COUNT(*) FROM (
                SELECT session_key FROM conversation_sessions
                GROUP BY session_key HAVING COUNT(*) > 1
            ) AS conflicts
        """,
        "multiple published menus for one restaurant": """
            SELECT COUNT(*) FROM (
                SELECT restaurant_id FROM menu_versions
                WHERE status = 'PUBLISHED'
                GROUP BY restaurant_id HAVING COUNT(*) > 1
            ) AS conflicts
        """,
        "menu item/modifier group version mismatch": """
            SELECT COUNT(*)
            FROM menu_item_modifier_groups link
            JOIN menu_items item ON item.id = link.menu_item_id
            JOIN modifier_groups modifier_group ON modifier_group.id = link.modifier_group_id
            WHERE item.menu_version_id <> modifier_group.menu_version_id
        """,
        "branch availability tenant mismatch": """
            SELECT COUNT(*)
            FROM branch_item_availability availability
            JOIN branches branch ON branch.id = availability.branch_id
            JOIN menu_items item ON item.id = availability.menu_item_id
            JOIN menu_versions version ON version.id = item.menu_version_id
            WHERE branch.restaurant_id <> version.restaurant_id
        """,
        "menu item allergen tenant or version mismatch": """
            SELECT COUNT(*)
            FROM menu_item_allergens declaration
            JOIN menu_items item ON item.id = declaration.menu_item_id
            JOIN menu_versions version ON version.id = declaration.menu_version_id
            JOIN allergens allergen ON allergen.id = declaration.allergen_id
            WHERE item.menu_version_id <> declaration.menu_version_id
               OR allergen.restaurant_id <> version.restaurant_id
        """,
        "order/customer tenant mismatch": """
            SELECT COUNT(*)
            FROM orders customer_order
            JOIN customers customer ON customer.id = customer_order.customer_id
            WHERE customer_order.customer_id IS NOT NULL
              AND customer.restaurant_id <> customer_order.restaurant_id
        """,
        "order/delivery zone branch mismatch": """
            SELECT COUNT(*)
            FROM orders delivery_order
            JOIN delivery_zones zone ON zone.id = delivery_order.delivery_zone_id
            WHERE delivery_order.delivery_zone_id IS NOT NULL
              AND zone.branch_id <> delivery_order.branch_id
        """,
        "order item tenant or version mismatch": """
            SELECT COUNT(*)
            FROM order_items order_item
            JOIN orders parent_order ON parent_order.id = order_item.order_id
            JOIN menu_items item ON item.id = order_item.menu_item_id
            JOIN menu_versions version ON version.id = order_item.menu_version_id
            WHERE item.menu_version_id <> order_item.menu_version_id
               OR version.restaurant_id <> parent_order.restaurant_id
        """,
        "idempotency branch tenant mismatch": """
            SELECT COUNT(*)
            FROM idempotency_records record
            JOIN branches branch ON branch.id = record.branch_id
            WHERE branch.restaurant_id <> record.restaurant_id
        """,
    }
    conflicts = [name for name, sql in checks.items() if int(bind.scalar(sa.text(sql)) or 0) > 0]
    if conflicts:
        raise RuntimeError(
            "Phase 2 integrity migration refused existing conflicting rows: " + "; ".join(conflicts)
        )


def upgrade() -> None:
    _assert_no_existing_conflicts()

    op.create_index(
        "uq_menu_versions_one_published_per_restaurant",
        "menu_versions",
        ["restaurant_id"],
        unique=True,
        sqlite_where=sa.text("status = 'PUBLISHED'"),
        postgresql_where=sa.text("status = 'PUBLISHED'"),
    )

    with op.batch_alter_table("modifier_groups") as batch_op:
        batch_op.create_unique_constraint("uq_modifier_groups_id_version", ["id", "menu_version_id"])
    with op.batch_alter_table("allergens") as batch_op:
        batch_op.create_unique_constraint("uq_allergens_id_restaurant", ["id", "restaurant_id"])
    with op.batch_alter_table("customers") as batch_op:
        batch_op.create_unique_constraint("uq_customers_id_restaurant", ["id", "restaurant_id"])
    with op.batch_alter_table("delivery_zones") as batch_op:
        batch_op.create_unique_constraint("uq_delivery_zones_id_branch", ["id", "branch_id"])
    with op.batch_alter_table("orders") as batch_op:
        batch_op.create_unique_constraint("uq_orders_id_restaurant", ["id", "restaurant_id"])
        batch_op.drop_constraint("fk_orders_customer_id_customers", type_="foreignkey")
        batch_op.drop_constraint("fk_orders_delivery_zone_id_delivery_zones", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_orders_customer_tenant",
            "customers",
            ["customer_id", "restaurant_id"],
            ["id", "restaurant_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_orders_delivery_zone_branch",
            "delivery_zones",
            ["delivery_zone_id", "branch_id"],
            ["id", "branch_id"],
            ondelete="RESTRICT",
        )

    op.add_column("menu_item_modifier_groups", sa.Column("menu_version_id", sa.Integer(), nullable=True))
    op.add_column("branch_item_availability", sa.Column("restaurant_id", sa.Integer(), nullable=True))
    op.add_column("branch_item_availability", sa.Column("menu_version_id", sa.Integer(), nullable=True))
    op.add_column("menu_item_allergens", sa.Column("restaurant_id", sa.Integer(), nullable=True))
    op.add_column("order_items", sa.Column("restaurant_id", sa.Integer(), nullable=True))

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE menu_item_modifier_groups
            SET menu_version_id = (
                SELECT menu_items.menu_version_id FROM menu_items
                WHERE menu_items.id = menu_item_modifier_groups.menu_item_id
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE branch_item_availability
            SET restaurant_id = (
                    SELECT branches.restaurant_id FROM branches
                    WHERE branches.id = branch_item_availability.branch_id
                ),
                menu_version_id = (
                    SELECT menu_items.menu_version_id FROM menu_items
                    WHERE menu_items.id = branch_item_availability.menu_item_id
                )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE menu_item_allergens
            SET restaurant_id = (
                SELECT allergens.restaurant_id FROM allergens
                WHERE allergens.id = menu_item_allergens.allergen_id
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE order_items
            SET restaurant_id = (
                SELECT orders.restaurant_id FROM orders
                WHERE orders.id = order_items.order_id
            )
            """
        )
    )

    with op.batch_alter_table("menu_item_modifier_groups") as batch_op:
        batch_op.drop_constraint("fk_menu_item_modifier_groups_menu_item_id_menu_items", type_="foreignkey")
        batch_op.drop_constraint("fk_menu_item_modifier_groups_modifier_group_id_modifier_groups", type_="foreignkey")
        batch_op.alter_column("menu_version_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_item_modifier_groups_item_version",
            "menu_items",
            ["menu_item_id", "menu_version_id"],
            ["id", "menu_version_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_item_modifier_groups_group_version",
            "modifier_groups",
            ["modifier_group_id", "menu_version_id"],
            ["id", "menu_version_id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("branch_item_availability") as batch_op:
        batch_op.drop_constraint("fk_branch_item_availability_branch_id_branches", type_="foreignkey")
        batch_op.drop_constraint("fk_branch_item_availability_menu_item_id_menu_items", type_="foreignkey")
        batch_op.alter_column("restaurant_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("menu_version_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_branch_item_availability_branch_tenant",
            "branches",
            ["branch_id", "restaurant_id"],
            ["id", "restaurant_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_branch_item_availability_item_version",
            "menu_items",
            ["menu_item_id", "menu_version_id"],
            ["id", "menu_version_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_branch_item_availability_version_tenant",
            "menu_versions",
            ["menu_version_id", "restaurant_id"],
            ["id", "restaurant_id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("menu_item_allergens") as batch_op:
        batch_op.drop_constraint("fk_menu_item_allergens_allergen_id_allergens", type_="foreignkey")
        batch_op.drop_constraint("fk_menu_item_allergens_menu_version_id_menu_versions", type_="foreignkey")
        batch_op.alter_column("restaurant_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_item_allergens_allergen_tenant",
            "allergens",
            ["allergen_id", "restaurant_id"],
            ["id", "restaurant_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_item_allergens_version_tenant",
            "menu_versions",
            ["menu_version_id", "restaurant_id"],
            ["id", "restaurant_id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("order_items") as batch_op:
        batch_op.drop_constraint("fk_order_items_order_id_orders", type_="foreignkey")
        batch_op.drop_constraint("fk_order_items_menu_item_id_menu_items", type_="foreignkey")
        batch_op.drop_constraint("fk_order_items_menu_version_id_menu_versions", type_="foreignkey")
        batch_op.alter_column("restaurant_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_foreign_key(
            "fk_order_items_order_tenant",
            "orders",
            ["order_id", "restaurant_id"],
            ["id", "restaurant_id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_order_items_item_version",
            "menu_items",
            ["menu_item_id", "menu_version_id"],
            ["id", "menu_version_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_order_items_version_tenant",
            "menu_versions",
            ["menu_version_id", "restaurant_id"],
            ["id", "restaurant_id"],
            ondelete="RESTRICT",
        )

    with op.batch_alter_table("idempotency_records") as batch_op:
        batch_op.drop_constraint("fk_idempotency_records_branch_id_branches", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_idempotency_branch_tenant",
            "branches",
            ["branch_id", "restaurant_id"],
            ["id", "restaurant_id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("conversation_sessions") as batch_op:
        batch_op.drop_constraint("uq_sessions_tenant_key", type_="unique")
        batch_op.create_unique_constraint("uq_sessions_global_key", ["session_key"])


def downgrade() -> None:
    with op.batch_alter_table("conversation_sessions") as batch_op:
        batch_op.drop_constraint("uq_sessions_global_key", type_="unique")
        batch_op.create_unique_constraint(
            "uq_sessions_tenant_key", ["restaurant_id", "branch_id", "session_key"]
        )

    with op.batch_alter_table("idempotency_records") as batch_op:
        batch_op.drop_constraint("fk_idempotency_branch_tenant", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_idempotency_records_branch_id_branches",
            "branches",
            ["branch_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("order_items") as batch_op:
        batch_op.drop_constraint("fk_order_items_order_tenant", type_="foreignkey")
        batch_op.drop_constraint("fk_order_items_item_version", type_="foreignkey")
        batch_op.drop_constraint("fk_order_items_version_tenant", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_order_items_order_id_orders", "orders", ["order_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_foreign_key(
            "fk_order_items_menu_item_id_menu_items",
            "menu_items",
            ["menu_item_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_order_items_menu_version_id_menu_versions",
            "menu_versions",
            ["menu_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.drop_column("restaurant_id")

    with op.batch_alter_table("menu_item_allergens") as batch_op:
        batch_op.drop_constraint("fk_item_allergens_allergen_tenant", type_="foreignkey")
        batch_op.drop_constraint("fk_item_allergens_version_tenant", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_menu_item_allergens_allergen_id_allergens",
            "allergens",
            ["allergen_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_menu_item_allergens_menu_version_id_menu_versions",
            "menu_versions",
            ["menu_version_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_column("restaurant_id")

    with op.batch_alter_table("branch_item_availability") as batch_op:
        batch_op.drop_constraint("fk_branch_item_availability_branch_tenant", type_="foreignkey")
        batch_op.drop_constraint("fk_branch_item_availability_item_version", type_="foreignkey")
        batch_op.drop_constraint("fk_branch_item_availability_version_tenant", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_branch_item_availability_branch_id_branches",
            "branches",
            ["branch_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_branch_item_availability_menu_item_id_menu_items",
            "menu_items",
            ["menu_item_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_column("menu_version_id")
        batch_op.drop_column("restaurant_id")

    with op.batch_alter_table("menu_item_modifier_groups") as batch_op:
        batch_op.drop_constraint("fk_item_modifier_groups_item_version", type_="foreignkey")
        batch_op.drop_constraint("fk_item_modifier_groups_group_version", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_menu_item_modifier_groups_menu_item_id_menu_items",
            "menu_items",
            ["menu_item_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_menu_item_modifier_groups_modifier_group_id_modifier_groups",
            "modifier_groups",
            ["modifier_group_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_column("menu_version_id")

    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("fk_orders_customer_tenant", type_="foreignkey")
        batch_op.drop_constraint("fk_orders_delivery_zone_branch", type_="foreignkey")
        batch_op.drop_constraint("uq_orders_id_restaurant", type_="unique")
        batch_op.create_foreign_key(
            "fk_orders_customer_id_customers",
            "customers",
            ["customer_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_orders_delivery_zone_id_delivery_zones",
            "delivery_zones",
            ["delivery_zone_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    with op.batch_alter_table("delivery_zones") as batch_op:
        batch_op.drop_constraint("uq_delivery_zones_id_branch", type_="unique")
    with op.batch_alter_table("customers") as batch_op:
        batch_op.drop_constraint("uq_customers_id_restaurant", type_="unique")
    with op.batch_alter_table("allergens") as batch_op:
        batch_op.drop_constraint("uq_allergens_id_restaurant", type_="unique")
    with op.batch_alter_table("modifier_groups") as batch_op:
        batch_op.drop_constraint("uq_modifier_groups_id_version", type_="unique")

    op.drop_index("uq_menu_versions_one_published_per_restaurant", table_name="menu_versions")
