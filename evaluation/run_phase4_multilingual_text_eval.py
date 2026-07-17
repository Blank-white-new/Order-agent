from __future__ import annotations

import argparse
import asyncio
import copy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
import uuid
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_DATASET = Path(__file__).with_name("phase4_multilingual_text.jsonl")
DEFAULT_LOCALE_DATASET = Path(__file__).with_name("phase4_locale_detection.jsonl")
OFFLINE_VARIABLES = (
    "LLM_FALLBACK_API_KEY",
    "LLM_FALLBACK_BASE_URL",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "LLM_FALLBACK_REPLAY_FILE",
    "LLM_FALLBACK_SHADOW_SOURCE",
)
TRACKED_MUTATION_FIELDS = (
    "current_order",
    "fulfillment_type",
    "official_delivery_address",
    "phone",
    "submitted",
    "submitted_order_id",
)
MODES = ("auto", "assisted")


def force_offline_environment() -> None:
    os.environ.update(
        {
            "LLM_FALLBACK_MODE": "disabled",
            "LLM_FALLBACK_ENABLED": "false",
            "LLM_FALLBACK_SPECULATIVE_ENABLED": "false",
            "ALLOW_LIVE_LLM": "false",
            "VOICE_ENABLED": "false",
            "TTS_ENABLED": "false",
            "SIMULATION_DATA_ONLY": "true",
            "BACKEND_ENV_FILE": str(
                Path(tempfile.gettempdir()) / f"phase4-eval-{os.getpid()}.env"
            ),
        }
    )
    for name in OFFLINE_VARIABLES:
        os.environ.pop(name, None)


force_offline_environment()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.agents.orchestrator import OrchestratorAgent  # noqa: E402
from app.db.config import DatabaseSettings  # noqa: E402
from app.db.models import (  # noqa: E402
    ConversationSession,
    IdempotencyRecord,
    MenuVersion,
    Order,
    OrderConfirmation,
)
from app.db.session import create_database  # noqa: E402
from app.domain.errors import DomainError  # noqa: E402
from app.i18n.menu_lexicon import MenuLexiconService  # noqa: E402
from app.i18n.message_catalog import MessageCatalog  # noqa: E402
from app.i18n.multilingual_text_service import MultilingualTextService  # noqa: E402
from app.i18n.response_renderer import ResponseRenderer  # noqa: E402
from app.repositories.uow import SqlAlchemyUnitOfWork  # noqa: E402
from app.services.handoff_provider import SimulationHandoffProvider  # noqa: E402
from app.services.handoff_service import HandoffService  # noqa: E402
from app.services.menu_service import MenuService  # noqa: E402
from app.services.order_persistence_service import OrderPersistenceService  # noqa: E402
from app.services.phase4_menu_seed_service import Phase4MenuSeedService  # noqa: E402
from app.services.safety_audit_service import SafetyAuditService  # noqa: E402
from app.services.safety_decision_service import SafetyDecisionService  # noqa: E402
from app.services.seed_service import seed_phase2_simulation_data  # noqa: E402
from app.services.tenant_service import TenantService  # noqa: E402
from app.services.text_entry_service import TextEntryService  # noqa: E402
from app.state.session_store import PersistentSessionStore  # noqa: E402


@dataclass
class Metrics:
    mode: str
    total: int = 0
    auto_locale_checks: int = 0
    auto_locale_matches: int = 0
    auto_dominant_locale_checks: int = 0
    auto_dominant_locale_matches: int = 0
    auto_response_locale_checks: int = 0
    auto_response_locale_matches: int = 0
    assisted_response_locale_checks: int = 0
    assisted_response_locale_matches: int = 0
    assisted_intent_checks: int = 0
    assisted_intent_matches: int = 0
    intent_checks: int = 0
    intent_matches: int = 0
    item_checks: int = 0
    item_matches: int = 0
    quantity_checks: int = 0
    quantity_matches: int = 0
    modifier_checks: int = 0
    modifier_matches: int = 0
    classification_checks: int = 0
    classification_matches: int = 0
    confirmation_checks: int = 0
    confirmation_matches: int = 0
    handoff_reason_checks: int = 0
    handoff_reason_matches: int = 0
    refusal_reason_checks: int = 0
    refusal_reason_matches: int = 0
    mutation_checks: int = 0
    mutation_matches: int = 0
    handoff_false_positives: int = 0
    refusal_false_positives: int = 0
    wrong_mutations: int = 0
    confirmation_bypasses: int = 0
    serious_allergy_omissions: int = 0
    fake_merchant_acceptance: int = 0
    duplicate_order_line_items: int = 0
    database_order_checks: int = 0
    database_order_matches: int = 0
    duplicate_database_orders: int = 0
    duplicate_order_confirmations: int = 0
    duplicate_idempotency_records: int = 0
    cross_tenant_refusal_checks: int = 0
    cross_tenant_refusal_errors: int = 0
    unsupported_language_failures: int = 0
    message_catalog_failures: int = 0
    live_llm_triggers: int = 0


@dataclass
class LocaleDetectionMetrics:
    total: int = 0
    exact_locale_checks: int = 0
    exact_locale_matches: int = 0
    dominant_locale_checks: int = 0
    dominant_locale_matches: int = 0
    response_locale_checks: int = 0
    response_locale_matches: int = 0
    ambiguous_checks: int = 0
    ambiguous_conservative_matches: int = 0
    unsupported_checks: int = 0
    unsupported_matches: int = 0


@dataclass
class TenantAccessMetrics:
    cross_tenant_data_access_checks: int = 0
    cross_tenant_data_leak_failures: int = 0


@dataclass
class EvalRuntime:
    database: Any
    service: TextEntryService
    uow_factory: Any
    tenant_service: TenantService
    multilingual_service: MultilingualTextService
    handoff_service: HandoffService


def migrate(database_url: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["skip_logging_config"] = True
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def create_service(database_url: str) -> EvalRuntime:
    settings = DatabaseSettings(
        app_env="test",
        database_url=database_url,
        database_echo=False,
        auto_migrate_local=False,
        simulation_data_only=True,
        default_restaurant_code="hk-sim-restaurant-a",
        default_branch_code="central",
    )
    database = create_database(settings)
    migrate(database.settings.database_url)
    uow_factory = lambda: SqlAlchemyUnitOfWork(database.session_factory)
    seed_phase2_simulation_data(uow_factory)
    Phase4MenuSeedService(uow_factory).seed()
    tenants = TenantService(uow_factory, database.settings)
    store = PersistentSessionStore(uow_factory, tenants)

    def orchestrator_for_tenant(restaurant_code, branch_code):
        return OrchestratorAgent(
            menu_service=MenuService(
                restaurant_code=restaurant_code,
                branch_code=branch_code,
                database=database,
            )
        )

    multilingual = MultilingualTextService(
        MenuLexiconService(uow_factory, tenants),
        ResponseRenderer(MessageCatalog(environment="test")),
    )
    handoff = HandoffService(uow_factory, tenants, SimulationHandoffProvider())
    service = TextEntryService(
        store=store,
        orchestrator=orchestrator_for_tenant(None, None),
        orchestrator_factory=orchestrator_for_tenant,
        order_persistence_service=OrderPersistenceService(
            uow_factory, tenants, simulation_data_only=True
        ),
        safety_audit_service=SafetyAuditService(
            uow_factory, tenants, SafetyDecisionService()
        ),
        handoff_service=handoff,
        multilingual_text_service=multilingual,
    )
    return EvalRuntime(
        database=database,
        service=service,
        uow_factory=uow_factory,
        tenant_service=tenants,
        multilingual_service=multilingual,
        handoff_service=handoff,
    )


def load_dataset(path: Path, *, minimum: int) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {number}: {exc}") from exc
    if len(rows) < minimum:
        raise ValueError(f"{path.name} requires at least {minimum} scenarios")
    return rows


def business_snapshot(state: dict) -> dict:
    return {key: copy.deepcopy(state.get(key)) for key in TRACKED_MUTATION_FIELDS}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))]


def build_request_kwargs(row: dict, mode: str, *, scenario_id: str) -> dict[str, Any]:
    """Build runtime inputs without consulting parser/classification ground truth."""
    if mode not in MODES:
        raise ValueError(f"unsupported evaluation mode: {mode}")
    kwargs: dict[str, Any] = {
        "restaurant_code": row["restaurant_code"],
        "branch_code": row["branch_code"],
        "idempotency_key": f"phase4-{mode}-{scenario_id}",
    }
    if mode == "assisted":
        selected = row.get("assisted_response_locale")
        if selected not in {"zh-CN", "yue-Hant-HK", "en-HK"}:
            raise ValueError(f"{scenario_id} has no concrete assisted_response_locale")
        kwargs.update({"locale": selected, "locale_locked": True})
    return kwargs


def expected_response_locale(row: dict, mode: str) -> str | None:
    return (
        row.get("expected_auto_response_locale", row.get("expected_response_locale"))
        if mode == "auto"
        else row.get("assisted_response_locale")
    )


def _line_identity(item: dict) -> str:
    identity = {
        "item_id": item.get("item_id"),
        "options": sorted(item.get("options") or []),
        "spicy_level": item.get("spicy_level"),
        "exclusions": sorted(item.get("exclusions") or []),
        "notes": item.get("notes"),
    }
    return json.dumps(identity, ensure_ascii=False, sort_keys=True)


def database_snapshot(runtime: EvalRuntime, session_key: str) -> dict[str, int]:
    with runtime.database.session_factory() as session:
        session_row = session.scalar(
            select(ConversationSession).where(
                ConversationSession.session_key == session_key
            )
        )
        if session_row is None:
            return {
                "orders": 0,
                "active_confirmations": 0,
                "duplicate_active_confirmations": 0,
                "duplicate_idempotency_records": 0,
            }
        order_ids = list(
            session.scalars(select(Order.id).where(Order.session_id == session_row.id))
        )
        active_counts = []
        if order_ids:
            active_counts = list(
                session.execute(
                    select(OrderConfirmation.order_id, func.count(OrderConfirmation.id))
                    .where(
                        OrderConfirmation.order_id.in_(order_ids),
                        OrderConfirmation.invalidated_at.is_(None),
                    )
                    .group_by(OrderConfirmation.order_id)
                )
            )
        duplicate_idempotency = session.execute(
            select(
                IdempotencyRecord.restaurant_id,
                IdempotencyRecord.branch_id,
                IdempotencyRecord.scope,
                IdempotencyRecord.idempotency_key,
                func.count(IdempotencyRecord.id),
            )
            .group_by(
                IdempotencyRecord.restaurant_id,
                IdempotencyRecord.branch_id,
                IdempotencyRecord.scope,
                IdempotencyRecord.idempotency_key,
            )
            .having(func.count(IdempotencyRecord.id) > 1)
        ).all()
        return {
            "orders": len(order_ids),
            "active_confirmations": sum(count for _order_id, count in active_counts),
            "duplicate_active_confirmations": sum(
                max(0, count - 1) for _order_id, count in active_counts
            ),
            "duplicate_idempotency_records": sum(
                count - 1 for *_scope, count in duplicate_idempotency
            ),
        }


async def evaluate(
    rows: list[dict], runtime: EvalRuntime, mode: str
) -> tuple[Metrics, list[dict], dict]:
    metrics = Metrics(mode=mode, total=len(rows))
    failures: list[dict] = []
    durations: list[float] = []
    for row in rows:
        session_id = f"phase4-eval-{mode}-{row['scenario_id']}-{uuid.uuid4().hex}"
        runtime_kwargs = build_request_kwargs(
            row, mode, scenario_id=row["scenario_id"]
        )
        for setup_index, setup in enumerate(row.get("setup_inputs", []), 1):
            setup_kwargs = dict(runtime_kwargs)
            setup_kwargs["idempotency_key"] = (
                f"phase4-{mode}-{row['scenario_id']}-setup-{setup_index}"
            )
            await runtime.service.handle_text_message(session_id, setup, **setup_kwargs)
        before_state = runtime.service.store.get(
            session_id, row["restaurant_code"], row["branch_code"]
        ).serializable()
        start = time.perf_counter()
        try:
            result = await runtime.service.handle_text_message(
                session_id, row["input"], **runtime_kwargs
            )
        except Exception as exc:  # evaluation records and fails closed
            metrics.message_catalog_failures += int(
                "catalog" in str(exc).casefold()
            )
            failures.append(
                {
                    "scenario_id": row["scenario_id"],
                    "mode": mode,
                    "error": type(exc).__name__,
                    "detail": str(exc)[:160],
                }
            )
            continue
        durations.append((time.perf_counter() - start) * 1000)
        parsed = result.get("trace", {}).get("multilingual", {})
        entities = parsed.get("entities", {})
        safety = result.get("trace", {}).get("safety", {})
        classification = (
            safety.get("classification")
            or result["raw_state"].safety_classification
        )
        reason = safety.get("reason_code") or result["raw_state"].safety_reason_code
        after_state = result["raw_state"].serializable()
        mutated = business_snapshot(before_state) != business_snapshot(after_state)
        expected_entities = row.get("expected_entities") or {}
        checks: dict[str, bool] = {}

        if mode == "auto" and not row.get("ambiguous_locale", False):
            expected_detected = row.get("expected_detected_locale")
            if expected_detected is not None:
                metrics.auto_locale_checks += 1
                checks["auto_locale"] = result.get("detected_locale") == expected_detected
                metrics.auto_locale_matches += checks["auto_locale"]
            expected_dominant = row.get("expected_dominant_locale")
            if expected_dominant is not None:
                metrics.auto_dominant_locale_checks += 1
                checks["auto_dominant_locale"] = (
                    result.get("dominant_locale") == expected_dominant
                )
                metrics.auto_dominant_locale_matches += checks[
                    "auto_dominant_locale"
                ]
            expected_response = expected_response_locale(row, mode)
            if expected_response is not None:
                metrics.auto_response_locale_checks += 1
                checks["auto_response_locale"] = (
                    result.get("response_locale") == expected_response
                )
                metrics.auto_response_locale_matches += checks[
                    "auto_response_locale"
                ]
        elif mode == "assisted":
            expected_response = expected_response_locale(row, mode)
            metrics.assisted_response_locale_checks += 1
            checks["assisted_response_locale"] = (
                result.get("response_locale") == expected_response
            )
            metrics.assisted_response_locale_matches += checks[
                "assisted_response_locale"
            ]
            if row.get("expected_intent") is not None:
                metrics.assisted_intent_checks += 1
                checks["assisted_intent"] = (
                    parsed.get("canonicalIntent") == row["expected_intent"]
                )
                metrics.assisted_intent_matches += checks["assisted_intent"]

        if row.get("expected_intent") is not None:
            metrics.intent_checks += 1
            checks["intent"] = parsed.get("canonicalIntent") == row["expected_intent"]
            metrics.intent_matches += checks["intent"]
        if row.get("expected_classification") is not None:
            metrics.classification_checks += 1
            checks["classification"] = (
                classification == row["expected_classification"]
            )
            metrics.classification_matches += checks["classification"]
        if row.get("expected_mutation") is not None:
            metrics.mutation_checks += 1
            checks["mutation"] = mutated == row["expected_mutation"]
            metrics.mutation_matches += checks["mutation"]
            if not row["expected_mutation"] and mutated:
                metrics.wrong_mutations += 1
        if "expected_confirmation_valid" in row:
            metrics.confirmation_checks += 1
            checks["confirmation"] = (
                result["raw_state"].confirmation_valid
                == row["expected_confirmation_valid"]
            )
            metrics.confirmation_matches += checks["confirmation"]

        expected_handoff = row.get("expected_handoff_reason")
        if expected_handoff is not None:
            metrics.handoff_reason_checks += 1
            checks["handoff_reason"] = (
                classification == "HANDOFF" and reason == expected_handoff
            )
            metrics.handoff_reason_matches += checks["handoff_reason"]
        elif classification == "HANDOFF":
            metrics.handoff_false_positives += 1
        expected_refusal = row.get("expected_refusal_reason")
        if expected_refusal is not None:
            metrics.refusal_reason_checks += 1
            checks["refusal_reason"] = (
                classification == "REFUSE" and reason == expected_refusal
            )
            metrics.refusal_reason_matches += checks["refusal_reason"]
        elif classification == "REFUSE":
            metrics.refusal_false_positives += 1

        if "item_code" in expected_entities:
            metrics.item_checks += 1
            checks["item"] = (
                entities.get("item_code") == expected_entities["item_code"]
            )
            metrics.item_matches += checks["item"]
        if "quantity" in expected_entities:
            metrics.quantity_checks += 1
            checks["quantity"] = (
                entities.get("quantity") == expected_entities["quantity"]
            )
            metrics.quantity_matches += checks["quantity"]
        if "modifier_option_code" in expected_entities:
            metrics.modifier_checks += 1
            modifier_codes = {
                value.get("option_code") for value in entities.get("modifiers", [])
            }
            checks["modifier"] = (
                expected_entities["modifier_option_code"] in modifier_codes
            )
            metrics.modifier_matches += checks["modifier"]

        selected = result.get("trace", {}).get("selectedHandler")
        if selected == "submit_order" and not before_state.get("confirmation_valid"):
            # The Orchestrator may set confirmation_valid during this exact explicit
            # confirmation. A bypass exists only if the parser did not see an
            # explicit confirmation for the current draft.
            if parsed.get("confirmationResult") != "EXPLICIT_CONFIRM":
                metrics.confirmation_bypasses += 1
        if expected_handoff == "SEVERE_ALLERGY" and not checks.get(
            "handoff_reason", False
        ):
            metrics.serious_allergy_omissions += 1
        if expected_refusal in {"CROSS_TENANT_ACCESS", "UNAUTHORIZED_ORDER_ACCESS"}:
            metrics.cross_tenant_refusal_checks += 1
            if not checks.get("refusal_reason", False):
                metrics.cross_tenant_refusal_errors += 1

        response_text = result.get("response", "").casefold()
        affirmative_acceptance = (
            "restaurant has accepted" in response_text
            or "merchant has accepted" in response_text
            or "商家已接受" in response_text
            and not any(
                negated in response_text
                for negated in (
                    "尚未获商家接受",
                    "不代表商家已接受",
                    "唔代表商家已接受",
                )
            )
        )
        if result.get("merchant_status") == "ACCEPTED" or affirmative_acceptance:
            metrics.fake_merchant_acceptance += 1

        order_lines = after_state.get("current_order") or []
        line_identities = [_line_identity(item) for item in order_lines]
        if len(line_identities) != len(set(line_identities)):
            metrics.duplicate_order_line_items += 1

        database = database_snapshot(runtime, session_id)
        expected_order_count = row.get("expected_database_order_count", 0)
        expected_confirmation_count = row.get(
            "expected_active_confirmation_count", 0
        )
        metrics.database_order_checks += 1
        checks["database_order_count"] = (
            database["orders"] == expected_order_count
            and database["active_confirmations"] == expected_confirmation_count
        )
        metrics.database_order_matches += checks["database_order_count"]
        metrics.duplicate_database_orders += max(
            0, database["orders"] - expected_order_count
        )
        metrics.duplicate_order_confirmations += database[
            "duplicate_active_confirmations"
        ]
        metrics.duplicate_idempotency_records += database[
            "duplicate_idempotency_records"
        ]

        if expected_handoff == "LANGUAGE_UNSUPPORTED" and not checks.get(
            "handoff_reason", False
        ):
            metrics.unsupported_language_failures += 1
        trace = result.get("trace", {})
        if trace.get("llmFallback", {}).get("attempted") or trace.get(
            "llmFallbackTriggered"
        ):
            metrics.live_llm_triggers += 1
        if not all(checks.values()):
            failures.append(
                {
                    "scenario_id": row["scenario_id"],
                    "mode": mode,
                    "failed": [key for key, value in checks.items() if not value],
                    "actual": {
                        "detected": result.get("detected_locale"),
                        "dominant": result.get("dominant_locale"),
                        "response": result.get("response_locale"),
                        "intent": parsed.get("canonicalIntent"),
                        "entities": entities,
                        "classification": classification,
                        "reason": reason,
                        "mutation": mutated,
                        "database": database,
                    },
                }
            )
    performance = {
        "p50Ms": round(statistics.median(durations), 3) if durations else 0,
        "p95Ms": round(percentile(durations, 0.95), 3),
        "maxMs": round(max(durations), 3) if durations else 0,
    }
    return metrics, failures, performance


async def evaluate_locale_detection(
    rows: list[dict], runtime: EvalRuntime
) -> tuple[LocaleDetectionMetrics, list[dict]]:
    metrics = LocaleDetectionMetrics(total=len(rows))
    failures: list[dict] = []
    for row in rows:
        session_id = f"phase4-locale-{row['scenario_id']}-{uuid.uuid4().hex}"
        base_kwargs = {
            "restaurant_code": row.get("restaurant_code", "hk-sim-restaurant-a"),
            "branch_code": row.get("branch_code", "central"),
        }
        for setup in row.get("setup_inputs", []):
            await runtime.service.handle_text_message(session_id, setup, **base_kwargs)
        result = await runtime.service.handle_text_message(
            session_id, row["input"], **base_kwargs
        )
        checks: dict[str, bool] = {}
        if row.get("ambiguous_locale", False):
            metrics.ambiguous_checks += 1
            allowed = set(row.get("allowed_detected_locales") or [])
            checks["ambiguous_conservative"] = (
                result.get("detected_locale") in allowed
                and result.get("response_locale") == row["expected_response_locale"]
            )
            metrics.ambiguous_conservative_matches += checks[
                "ambiguous_conservative"
            ]
        else:
            metrics.exact_locale_checks += 1
            checks["exact_locale"] = (
                result.get("detected_locale") == row["expected_detected_locale"]
            )
            metrics.exact_locale_matches += checks["exact_locale"]
        if row.get("expected_dominant_locale") is not None:
            metrics.dominant_locale_checks += 1
            checks["dominant_locale"] = (
                result.get("dominant_locale") == row["expected_dominant_locale"]
            )
            metrics.dominant_locale_matches += checks["dominant_locale"]
        metrics.response_locale_checks += 1
        checks["response_locale"] = (
            result.get("response_locale") == row["expected_response_locale"]
        )
        metrics.response_locale_matches += checks["response_locale"]
        if row.get("expected_detected_locale") == "und":
            metrics.unsupported_checks += 1
            checks["unsupported"] = result.get("detected_locale") == "und"
            metrics.unsupported_matches += checks["unsupported"]
        if not all(checks.values()):
            failures.append(
                {
                    "scenario_id": row["scenario_id"],
                    "failed": [key for key, value in checks.items() if not value],
                    "actual": {
                        "detected": result.get("detected_locale"),
                        "dominant": result.get("dominant_locale"),
                        "response": result.get("response_locale"),
                    },
                }
            )
    return metrics, failures


async def audit_cross_tenant_data_access(runtime: EvalRuntime) -> TenantAccessMetrics:
    metrics = TenantAccessMetrics()
    session_id = f"phase4-tenant-audit-{uuid.uuid4().hex}"
    tenant_a = ("hk-sim-restaurant-a", "central")
    tenant_b = ("hk-sim-restaurant-b", "north")
    for text in ("给我来两份鸡腿盖饭", "改成自取", "确认订单"):
        confirmed = await runtime.service.handle_text_message(
            session_id,
            text,
            restaurant_code=tenant_a[0],
            branch_code=tenant_a[1],
            idempotency_key=f"tenant-audit-{session_id}",
        )
    public_id = confirmed["raw_state"].submitted_order_id
    handoff_session = f"{session_id}-handoff"
    handoff = await runtime.service.handle_text_message(
        handoff_session,
        "我有严重过敏，可能过敏性休克",
        restaurant_code=tenant_a[0],
        branch_code=tenant_a[1],
    )
    handoff_id = handoff["raw_state"].handoff_public_id

    def record(value: bool) -> None:
        metrics.cross_tenant_data_access_checks += 1
        if not value:
            metrics.cross_tenant_data_leak_failures += 1

    with runtime.database.session_factory() as session:
        before_counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (ConversationSession, Order, OrderConfirmation, IdempotencyRecord)
        }

    for restaurant_code, branch_code in (
        tenant_b,
        (tenant_a[0], "east"),
    ):
        try:
            runtime.service.store.get(session_id, restaurant_code, branch_code)
        except DomainError as exc:
            record(
                exc.code == "TENANT_CONTEXT_MISMATCH"
                and public_id not in exc.message
                and "鸡腿饭" not in exc.message
            )
        else:
            record(False)

    for restaurant_code, branch_code in (
        tenant_b,
        (tenant_a[0], "east"),
    ):
        try:
            await runtime.service.handle_text_message(
                session_id,
                "查看订单",
                restaurant_code=restaurant_code,
                branch_code=branch_code,
            )
        except DomainError as exc:
            record(
                exc.code == "TENANT_CONTEXT_MISMATCH"
                and public_id not in exc.message
                and "鸡腿饭" not in exc.message
            )
        else:
            record(False)

    a = runtime.tenant_service.resolve(*tenant_a)
    b = runtime.tenant_service.resolve(*tenant_b)
    east = runtime.tenant_service.resolve(tenant_a[0], "east")
    with runtime.uow_factory() as uow:
        record(uow.orders.get_by_public_id(public_id, b.restaurant_id, b.branch_id) is None)
        record(
            uow.orders.get_by_public_id(
                public_id, east.restaurant_id, east.branch_id
            )
            is None
        )

    for restaurant_code, branch_code in (tenant_b, (tenant_a[0], "east")):
        try:
            runtime.handoff_service.get(
                handoff_id,
                restaurant_code,
                branch_code,
                handoff_session,
            )
        except DomainError as exc:
            record(
                exc.code == "HANDOFF_NOT_FOUND"
                and handoff_id not in exc.message
                and public_id not in exc.message
            )
        else:
            record(False)

    b_entries = runtime.multilingual_service.menu_lexicon_service.entries(*tenant_b)
    with runtime.database.session_factory() as session:
        b_versions = set(
            session.scalars(
                select(MenuVersion.id).where(
                    MenuVersion.restaurant_id == b.restaurant_id
                )
            )
        )
    record(bool(b_entries) and {entry.menu_version_id for entry in b_entries} <= b_versions)

    with runtime.database.session_factory() as session:
        after_counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (ConversationSession, Order, OrderConfirmation, IdempotencyRecord)
        }
    record(before_counts == after_counts)
    return metrics


def _ratio_ok(checks: int, matches: int, *, required: bool = True) -> bool:
    return checks > 0 and matches == checks if required else checks == 0 or matches == checks


def gates_pass(metrics: Metrics) -> bool:
    ratios = (
        (metrics.intent_checks, metrics.intent_matches),
        (metrics.classification_checks, metrics.classification_matches),
        (metrics.item_checks, metrics.item_matches),
        (metrics.quantity_checks, metrics.quantity_matches),
        (metrics.modifier_checks, metrics.modifier_matches),
        (metrics.confirmation_checks, metrics.confirmation_matches),
        (metrics.handoff_reason_checks, metrics.handoff_reason_matches),
        (metrics.refusal_reason_checks, metrics.refusal_reason_matches),
        (metrics.mutation_checks, metrics.mutation_matches),
        (metrics.database_order_checks, metrics.database_order_matches),
    )
    mode_ratios = (
        (
            metrics.auto_locale_checks,
            metrics.auto_locale_matches,
            metrics.auto_response_locale_checks,
            metrics.auto_response_locale_matches,
        )
        if metrics.mode == "auto"
        else (
            metrics.assisted_response_locale_checks,
            metrics.assisted_response_locale_matches,
            metrics.assisted_intent_checks,
            metrics.assisted_intent_matches,
        )
    )
    zero = (
        metrics.handoff_false_positives,
        metrics.refusal_false_positives,
        metrics.wrong_mutations,
        metrics.confirmation_bypasses,
        metrics.serious_allergy_omissions,
        metrics.fake_merchant_acceptance,
        metrics.duplicate_order_line_items,
        metrics.duplicate_database_orders,
        metrics.duplicate_order_confirmations,
        metrics.duplicate_idempotency_records,
        metrics.cross_tenant_refusal_errors,
        metrics.unsupported_language_failures,
        metrics.message_catalog_failures,
        metrics.live_llm_triggers,
    )
    return (
        metrics.total >= 360
        and all(_ratio_ok(checks, matches) for checks, matches in ratios)
        and (
            metrics.mode != "auto"
            or _ratio_ok(
                metrics.auto_dominant_locale_checks,
                metrics.auto_dominant_locale_matches,
            )
        )
        and mode_ratios[0] > 0
        and mode_ratios[0] == mode_ratios[1]
        and mode_ratios[2] > 0
        and mode_ratios[2] == mode_ratios[3]
        and all(value == 0 for value in zero)
    )


def locale_gates_pass(metrics: LocaleDetectionMetrics) -> bool:
    return all(
        _ratio_ok(checks, matches, required=False)
        for checks, matches in (
            (metrics.exact_locale_checks, metrics.exact_locale_matches),
            (metrics.dominant_locale_checks, metrics.dominant_locale_matches),
            (metrics.response_locale_checks, metrics.response_locale_matches),
            (metrics.ambiguous_checks, metrics.ambiguous_conservative_matches),
            (metrics.unsupported_checks, metrics.unsupported_matches),
        )
    )


def not_evaluated_metrics(metrics: Metrics) -> list[str]:
    values = asdict(metrics)
    return sorted(
        name.removesuffix("_checks")
        for name, value in values.items()
        if name.endswith("_checks") and value == 0
    )


def metrics_report(metrics: Metrics, performance: dict) -> dict:
    report = asdict(metrics)
    report["not_evaluated"] = not_evaluated_metrics(metrics)
    report["performance"] = performance
    report["passed"] = gates_pass(metrics)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--locale-dataset", type=Path, default=DEFAULT_LOCALE_DATASET
    )
    parser.add_argument("--mode", choices=("auto", "assisted", "both"), default="both")
    parser.add_argument("--failures", type=Path)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    rows = load_dataset(args.dataset, minimum=360)
    locale_rows = (
        load_dataset(args.locale_dataset, minimum=160)
        if args.locale_dataset.exists()
        else []
    )
    modes = MODES if args.mode == "both" else (args.mode,)
    all_failures: list[dict] = []
    mode_reports: dict[str, dict] = {}
    with tempfile.TemporaryDirectory(prefix="phase4-text-eval-") as directory:
        database_url = args.database_url or f"sqlite:///{Path(directory, 'eval.db').as_posix()}"
        runtime = create_service(database_url)
        try:
            for mode in modes:
                metrics, failures, performance = asyncio.run(
                    evaluate(rows, runtime, mode)
                )
                mode_reports[mode] = metrics_report(metrics, performance)
                all_failures.extend(failures)
            locale_metrics = None
            if "auto" in modes and locale_rows:
                locale_metrics, failures = asyncio.run(
                    evaluate_locale_detection(locale_rows, runtime)
                )
                all_failures.extend(failures)
            tenant_metrics = asyncio.run(audit_cross_tenant_data_access(runtime))
        finally:
            runtime.database.engine.dispose()

    passed = (
        all(report["passed"] for report in mode_reports.values())
        and tenant_metrics.cross_tenant_data_access_checks > 0
        and tenant_metrics.cross_tenant_data_leak_failures == 0
        and (locale_metrics is None or locale_gates_pass(locale_metrics))
    )
    report: dict[str, Any] = {
        **mode_reports,
        "cross_tenant_data_access": asdict(tenant_metrics),
        "passed": passed,
        "failure_count": len(all_failures),
    }
    if locale_metrics is not None:
        report["locale_detection_special"] = {
            **asdict(locale_metrics),
            "passed": locale_gates_pass(locale_metrics),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if all_failures:
        target = args.failures or (
            Path(tempfile.gettempdir()) / "phase4_multilingual_eval_failures.json"
        )
        target.write_text(
            json.dumps(all_failures, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"failure details: {target}", file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
