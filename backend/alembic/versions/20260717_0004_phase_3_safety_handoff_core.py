"""add phase 3 safety decisions and simulated handoff persistence

Revision ID: 20260717_0004
Revises: 20260717_0003
Create Date: 2026-07-17 18:30:00+00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260717_0004"
down_revision = "20260717_0003"
branch_labels = None
depends_on = None


ACTIVE_HANDOFF_SQL = (
    "status in ('REQUESTED','PENDING','SIMULATED_AGENT_ASSIGNED','SIMULATED_AGENT_CONNECTED')"
)


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.create_unique_constraint("uq_orders_id_tenant", ["id", "restaurant_id", "branch_id"])
        batch_op.add_column(
            sa.Column("safety_hold", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(sa.Column("safety_hold_reason", sa.String(length=80), nullable=True))

    op.create_table(
        "safety_session_counters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("consecutive_low_confidence", sa.Integer(), nullable=False),
        sa.Column("consecutive_misunderstandings", sa.Integer(), nullable=False),
        sa.Column("consecutive_corrections", sa.Integer(), nullable=False),
        sa.Column("confirmation_failures", sa.Integer(), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confirmation_failures >= 0", name=op.f("ck_safety_session_counters_confirmation_failures_nonnegative")
        ),
        sa.CheckConstraint(
            "consecutive_corrections >= 0", name=op.f("ck_safety_session_counters_corrections_nonnegative")
        ),
        sa.CheckConstraint(
            "consecutive_low_confidence >= 0", name=op.f("ck_safety_session_counters_low_confidence_nonnegative")
        ),
        sa.CheckConstraint(
            "consecutive_misunderstandings >= 0", name=op.f("ck_safety_session_counters_misunderstandings_nonnegative")
        ),
        sa.CheckConstraint("is_synthetic = true", name=op.f("ck_safety_session_counters_synthetic_only")),
        sa.ForeignKeyConstraint(
            ["session_id", "restaurant_id", "branch_id"],
            ["conversation_sessions.id", "conversation_sessions.restaurant_id", "conversation_sessions.branch_id"],
            name="fk_safety_counters_session_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_safety_session_counters")),
        sa.UniqueConstraint("session_id", name="uq_safety_counters_session"),
    )
    op.create_index(
        "ix_safety_counters_tenant", "safety_session_counters", ["restaurant_id", "branch_id"], unique=False
    )

    op.create_table(
        "safety_decision_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("classification", sa.String(length=24), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=True),
        sa.Column("explanation_code", sa.String(length=80), nullable=False),
        sa.Column("confidence_summary_json", sa.JSON(), nullable=False),
        sa.Column("required_confirmations_json", sa.JSON(), nullable=False),
        sa.Column("risk_ids_json", sa.JSON(), nullable=False),
        sa.Column("blocked_actions_json", sa.JSON(), nullable=False),
        sa.Column("metric_ids_json", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "classification in ('AUTO_DRAFT','CONFIRM','HANDOFF','REFUSE')",
            name=op.f("ck_safety_decision_records_classification_valid"),
        ),
        sa.CheckConstraint(
            "(classification in ('HANDOFF','REFUSE') and reason_code is not null) or "
            "(classification in ('AUTO_DRAFT','CONFIRM') and reason_code is null)",
            name=op.f("ck_safety_decision_records_classification_reason_consistent"),
        ),
        sa.CheckConstraint(
            "reason_code is null or reason_code in ('EXPLICIT_HUMAN_REQUEST','SEVERE_ALLERGY',"
            "'CROSS_CONTAMINATION','REPEATED_MISUNDERSTANDING','AMBIGUOUS_ITEM','AMBIGUOUS_QUANTITY',"
            "'UNVERIFIED_ADDRESS','PRICE_UNAVAILABLE','MENU_DATA_MISSING','COMPLAINT','REFUND_REQUEST',"
            "'PAYMENT_DISPUTE','MERCHANT_REJECTED','MERCHANT_TIMEOUT','SYSTEM_FAILURE','LANGUAGE_UNSUPPORTED',"
            "'ABUSE_OR_SECURITY','REGULATED_ITEM','CROSS_TENANT_ACCESS','UNAUTHORIZED_ORDER_ACCESS',"
            "'FORGE_MERCHANT_ACCEPTANCE','BYPASS_CONFIRMATION','CARD_DATA_STORAGE',"
            "'UNSUPPORTED_SAFETY_GUARANTEE','INTERNAL_SECRET_EXTRACTION','SECURITY_ATTACK')",
            name=op.f("ck_safety_decision_records_reason_valid"),
        ),
        sa.CheckConstraint("is_synthetic = true", name=op.f("ck_safety_decision_records_synthetic_only")),
        sa.ForeignKeyConstraint(
            ["order_id", "restaurant_id", "branch_id"],
            ["orders.id", "orders.restaurant_id", "orders.branch_id"],
            name="fk_safety_decisions_order_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "restaurant_id", "branch_id"],
            ["conversation_sessions.id", "conversation_sessions.restaurant_id", "conversation_sessions.branch_id"],
            name="fk_safety_decisions_session_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_safety_decision_records")),
        sa.UniqueConstraint("public_id", name="uq_safety_decisions_public_id"),
    )
    op.create_index(
        "ix_safety_decisions_session_created",
        "safety_decision_records",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_safety_decisions_tenant_class",
        "safety_decision_records",
        ["restaurant_id", "branch_id", "classification"],
        unique=False,
    )

    op.create_table(
        "handoff_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.String(length=64), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("decision_classification", sa.String(length=24), nullable=False),
        sa.Column("risk_ids_json", sa.JSON(), nullable=False),
        sa.Column("blocked_actions_json", sa.JSON(), nullable=False),
        sa.Column("summary_version", sa.Integer(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("resolution_json", sa.JSON(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision_classification = 'HANDOFF'", name=op.f("ck_handoff_cases_classification_handoff")
        ),
        sa.CheckConstraint("is_synthetic = true", name=op.f("ck_handoff_cases_synthetic_only")),
        sa.CheckConstraint(
            "priority in ('LOW','NORMAL','HIGH','CRITICAL')", name=op.f("ck_handoff_cases_priority_valid")
        ),
        sa.CheckConstraint(
            "failure_code is null or failure_code in ('NO_AGENT_AVAILABLE','QUEUE_TIMEOUT','ASSIGNMENT_FAILED',"
            "'CONNECTION_FAILED','CASE_CANCELLED','SYSTEM_ERROR')",
            name=op.f("ck_handoff_cases_failure_code_valid"),
        ),
        sa.CheckConstraint(
            "reason_code in ('EXPLICIT_HUMAN_REQUEST','SEVERE_ALLERGY','CROSS_CONTAMINATION',"
            "'REPEATED_MISUNDERSTANDING','AMBIGUOUS_ITEM','AMBIGUOUS_QUANTITY','UNVERIFIED_ADDRESS',"
            "'PRICE_UNAVAILABLE','MENU_DATA_MISSING','COMPLAINT','REFUND_REQUEST','PAYMENT_DISPUTE',"
            "'MERCHANT_REJECTED','MERCHANT_TIMEOUT','SYSTEM_FAILURE','LANGUAGE_UNSUPPORTED',"
            "'ABUSE_OR_SECURITY','REGULATED_ITEM')",
            name=op.f("ck_handoff_cases_reason_valid"),
        ),
        sa.CheckConstraint(
            "status in ('NOT_REQUIRED','REQUESTED','PENDING','SIMULATED_AGENT_ASSIGNED',"
            "'SIMULATED_AGENT_CONNECTED','RESOLVED','FAILED','CANCELLED')",
            name=op.f("ck_handoff_cases_status_valid"),
        ),
        sa.CheckConstraint("summary_version > 0", name=op.f("ck_handoff_cases_summary_version_positive")),
        sa.ForeignKeyConstraint(
            ["order_id", "restaurant_id", "branch_id"],
            ["orders.id", "orders.restaurant_id", "orders.branch_id"],
            name="fk_handoff_cases_order_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "restaurant_id", "branch_id"],
            ["conversation_sessions.id", "conversation_sessions.restaurant_id", "conversation_sessions.branch_id"],
            name="fk_handoff_cases_session_tenant",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_handoff_cases")),
        sa.UniqueConstraint("public_id", name="uq_handoff_cases_public_id"),
    )
    op.create_index(
        "ix_handoff_cases_tenant_status", "handoff_cases", ["restaurant_id", "branch_id", "status"], unique=False
    )
    op.create_index(
        "uq_handoff_cases_active_session",
        "handoff_cases",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text(ACTIVE_HANDOFF_SQL),
        postgresql_where=sa.text(ACTIVE_HANDOFF_SQL),
    )

    op.create_table(
        "handoff_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("handoff_case_id", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor_type in ('CUSTOMER','ORCHESTRATOR','SIMULATION_PROVIDER','SYSTEM')",
            name=op.f("ck_handoff_events_actor_type_valid"),
        ),
        sa.CheckConstraint("sequence_number > 0", name=op.f("ck_handoff_events_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["handoff_case_id"],
            ["handoff_cases.id"],
            name=op.f("fk_handoff_events_handoff_case_id_handoff_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_handoff_events")),
        sa.UniqueConstraint("handoff_case_id", "sequence_number", name="uq_handoff_events_sequence"),
    )
    op.create_index(
        "ix_handoff_events_case_occurred",
        "handoff_events",
        ["handoff_case_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_handoff_events_case_occurred", table_name="handoff_events")
    op.drop_table("handoff_events")
    op.drop_index("uq_handoff_cases_active_session", table_name="handoff_cases")
    op.drop_index("ix_handoff_cases_tenant_status", table_name="handoff_cases")
    op.drop_table("handoff_cases")
    op.drop_index("ix_safety_decisions_tenant_class", table_name="safety_decision_records")
    op.drop_index("ix_safety_decisions_session_created", table_name="safety_decision_records")
    op.drop_table("safety_decision_records")
    op.drop_index("ix_safety_counters_tenant", table_name="safety_session_counters")
    op.drop_table("safety_session_counters")

    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_column("safety_hold_reason")
        batch_op.drop_column("safety_hold")
        batch_op.drop_constraint("uq_orders_id_tenant", type_="unique")
