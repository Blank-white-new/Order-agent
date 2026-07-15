"""separate synthetic conversation contact snapshots

Revision ID: 20260716_0002
Revises: 20260716_0001
Create Date: 2026-07-16 01:30:00+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260716_0002"
down_revision = "20260716_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_contact_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("official_delivery_address", sa.String(length=500), nullable=True),
        sa.Column("pending_delivery_address_json", sa.JSON(), nullable=True),
        sa.Column("phone", sa.String(length=80), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.id"],
            name=op.f("fk_conversation_contact_snapshots_session_id_conversation_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_contact_snapshots")),
        sa.UniqueConstraint("session_id", name="uq_contact_snapshots_session"),
    )
    op.create_index(
        "ix_contact_snapshots_synthetic",
        "conversation_contact_snapshots",
        ["is_synthetic"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_contact_snapshots_synthetic", table_name="conversation_contact_snapshots")
    op.drop_table("conversation_contact_snapshots")
