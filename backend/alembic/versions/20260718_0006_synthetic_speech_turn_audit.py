"""add synthetic speech turn audit metadata

Revision ID: 20260718_0006
Revises: 20260718_0005
Create Date: 2026-07-18 04:00:00+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260718_0006"
down_revision = "20260718_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "speech_turn_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("provider_name", sa.String(length=80), nullable=False),
        sa.Column("provider_mode", sa.String(length=16), nullable=False),
        sa.Column("audio_encoding", sa.String(length=32), nullable=False),
        sa.Column("sample_rate_hz", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("audio_sha256", sa.String(length=64), nullable=False),
        sa.Column("fixture_id", sa.String(length=160), nullable=True),
        sa.Column("detected_locale", sa.String(length=32), nullable=True),
        sa.Column("response_locale", sa.String(length=32), nullable=True),
        sa.Column("confidence_bucket", sa.String(length=24), nullable=True),
        sa.Column("decision_classification", sa.String(length=24), nullable=True),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=80), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("direction in ('INPUT','OUTPUT')", name=op.f("ck_speech_turn_records_direction_valid")),
        sa.CheckConstraint("provider_mode in ('DISABLED','REPLAY','LOCAL','LIVE')", name=op.f("ck_speech_turn_records_provider_mode_valid")),
        sa.CheckConstraint("outcome in ('SUCCESS','NO_SPEECH','LOW_CONFIDENCE','TRUNCATED','PROVIDER_TIMEOUT','PROVIDER_ERROR','UNSUPPORTED_LANGUAGE','VALIDATION_ERROR')", name=op.f("ck_speech_turn_records_outcome_valid")),
        sa.CheckConstraint("duration_ms is null or duration_ms >= 0", name=op.f("ck_speech_turn_records_duration_nonnegative")),
        sa.CheckConstraint("sample_rate_hz > 0", name=op.f("ck_speech_turn_records_sample_rate_positive")),
        sa.CheckConstraint("length(audio_sha256) = 64", name=op.f("ck_speech_turn_records_audio_sha256_length")),
        sa.CheckConstraint("is_synthetic = true", name=op.f("ck_speech_turn_records_synthetic_only")),
        sa.ForeignKeyConstraint(["order_id", "restaurant_id", "branch_id"], ["orders.id", "orders.restaurant_id", "orders.branch_id"], name="fk_speech_turns_order_tenant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["session_id", "restaurant_id", "branch_id"], ["conversation_sessions.id", "conversation_sessions.restaurant_id", "conversation_sessions.branch_id"], name="fk_speech_turns_session_tenant", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_speech_turn_records")),
        sa.UniqueConstraint("public_id", name="uq_speech_turns_public_id"),
    )
    op.create_index("ix_speech_turns_session_created", "speech_turn_records", ["session_id", "created_at"], unique=False)
    op.create_index("ix_speech_turns_tenant_outcome", "speech_turn_records", ["restaurant_id", "branch_id", "outcome"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_speech_turns_tenant_outcome", table_name="speech_turn_records")
    op.drop_index("ix_speech_turns_session_created", table_name="speech_turn_records")
    op.drop_table("speech_turn_records")
