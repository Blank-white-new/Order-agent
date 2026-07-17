"""add version-scoped multilingual modifier translations

Revision ID: 20260718_0005
Revises: 20260717_0004
Create Date: 2026-07-18 01:30:00+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260718_0005"
down_revision = "20260717_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("modifier_options") as batch_op:
        batch_op.create_unique_constraint("uq_modifier_options_id_group", ["id", "modifier_group_id"])

    op.create_table(
        "modifier_group_translations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("modifier_group_id", sa.Integer(), nullable=False),
        sa.Column("menu_version_id", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["modifier_group_id", "menu_version_id"],
            ["modifier_groups.id", "modifier_groups.menu_version_id"],
            name="fk_modifier_group_translations_group_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modifier_group_translations")),
        sa.UniqueConstraint(
            "modifier_group_id", "locale", name="uq_modifier_group_translations_locale"
        ),
    )
    op.create_index(
        "ix_modifier_group_translations_version_locale",
        "modifier_group_translations",
        ["menu_version_id", "locale"],
        unique=False,
    )

    op.create_table(
        "modifier_option_translations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("modifier_option_id", sa.Integer(), nullable=False),
        sa.Column("modifier_group_id", sa.Integer(), nullable=False),
        sa.Column("menu_version_id", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["modifier_option_id", "modifier_group_id"],
            ["modifier_options.id", "modifier_options.modifier_group_id"],
            name="fk_modifier_option_translations_option_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["modifier_group_id", "menu_version_id"],
            ["modifier_groups.id", "modifier_groups.menu_version_id"],
            name="fk_modifier_option_translations_group_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modifier_option_translations")),
        sa.UniqueConstraint(
            "modifier_option_id", "locale", name="uq_modifier_option_translations_locale"
        ),
    )
    op.create_index(
        "ix_modifier_option_translations_version_locale",
        "modifier_option_translations",
        ["menu_version_id", "locale"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_modifier_option_translations_version_locale", table_name="modifier_option_translations"
    )
    op.drop_table("modifier_option_translations")
    op.drop_index(
        "ix_modifier_group_translations_version_locale", table_name="modifier_group_translations"
    )
    op.drop_table("modifier_group_translations")
    with op.batch_alter_table("modifier_options") as batch_op:
        batch_op.drop_constraint("uq_modifier_options_id_group", type_="unique")
