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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_DATASET = Path(__file__).with_name("phase4_multilingual_text.jsonl")
OFFLINE_VARIABLES = (
    "LLM_FALLBACK_API_KEY", "LLM_FALLBACK_BASE_URL", "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_PROVIDER", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL", "LLM_FALLBACK_REPLAY_FILE", "LLM_FALLBACK_SHADOW_SOURCE",
)
TRACKED_MUTATION_FIELDS = (
    "current_order", "fulfillment_type", "official_delivery_address", "phone",
    "submitted", "submitted_order_id",
)


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
            "BACKEND_ENV_FILE": str(Path(tempfile.gettempdir()) / f"phase4-eval-{os.getpid()}.env"),
        }
    )
    for name in OFFLINE_VARIABLES:
        os.environ.pop(name, None)


force_offline_environment()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.agents.orchestrator import OrchestratorAgent  # noqa: E402
from app.db.config import DatabaseSettings  # noqa: E402
from app.db.session import create_database  # noqa: E402
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
    total: int = 0
    locale_detection_matches: int = 0
    response_locale_matches: int = 0
    intent_matches: int = 0
    item_matches: int = 0
    item_checks: int = 0
    quantity_matches: int = 0
    quantity_checks: int = 0
    modifier_matches: int = 0
    modifier_checks: int = 0
    classification_matches: int = 0
    handoff_reason_matches: int = 0
    refusal_matches: int = 0
    expected_mutation_matches: int = 0
    wrong_mutations: int = 0
    confirmation_bypasses: int = 0
    serious_allergy_omissions: int = 0
    cross_tenant_leaks: int = 0
    fake_merchant_acceptance: int = 0
    duplicate_orders: int = 0
    unsupported_language_failures: int = 0
    message_catalog_failures: int = 0
    live_llm_triggers: int = 0


def migrate(database_url: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["skip_logging_config"] = True
    config.attributes["database_url"] = database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")


def create_service(database_url: str):
    settings = DatabaseSettings(
        app_env="test", database_url=database_url, database_echo=False,
        auto_migrate_local=False, simulation_data_only=True,
        default_restaurant_code="hk-sim-restaurant-a", default_branch_code="central",
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

    safety = SafetyDecisionService()
    service = TextEntryService(
        store=store,
        orchestrator=orchestrator_for_tenant(None, None),
        orchestrator_factory=orchestrator_for_tenant,
        order_persistence_service=OrderPersistenceService(uow_factory, tenants, simulation_data_only=True),
        safety_audit_service=SafetyAuditService(uow_factory, tenants, safety),
        handoff_service=HandoffService(uow_factory, tenants, SimulationHandoffProvider()),
        multilingual_text_service=MultilingualTextService(
            MenuLexiconService(uow_factory, tenants),
            ResponseRenderer(MessageCatalog(environment="test")),
        ),
    )
    return database, service


def load_dataset(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {number}: {exc}") from exc
    if len(rows) < 360:
        raise ValueError("Phase 4 evaluation requires at least 360 scenarios")
    return rows


def business_snapshot(state: dict) -> dict:
    return {key: copy.deepcopy(state.get(key)) for key in TRACKED_MUTATION_FIELDS}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * fraction)))]


async def evaluate(rows: list[dict], service: TextEntryService) -> tuple[Metrics, list[dict], dict]:
    metrics = Metrics(total=len(rows))
    failures: list[dict] = []
    durations: list[float] = []
    for row in rows:
        session_id = f"phase4-eval-{row['scenario_id']}-{uuid.uuid4().hex}"
        locale_hint = None if row["locale"] == "mixed" else row["locale"]
        requested_locale = None if row["locale"] == "mixed" else row["locale"]
        for setup in row.get("setup_inputs", []):
            await service.handle_text_message(
                session_id, setup,
                restaurant_code=row["restaurant_code"], branch_code=row["branch_code"],
                locale=requested_locale, locale_hint=locale_hint, locale_locked=False,
            )
        before_state = service.store.get(
            session_id, row["restaurant_code"], row["branch_code"]
        ).serializable()
        start = time.perf_counter()
        try:
            result = await service.handle_text_message(
                session_id, row["input"],
                restaurant_code=row["restaurant_code"], branch_code=row["branch_code"],
                locale=requested_locale, locale_hint=locale_hint, locale_locked=False,
            )
        except Exception as exc:  # evaluation records and fails closed
            metrics.message_catalog_failures += int("catalog" in str(exc).casefold())
            failures.append({"scenario_id": row["scenario_id"], "error": type(exc).__name__, "detail": str(exc)[:160]})
            continue
        durations.append((time.perf_counter() - start) * 1000)
        parsed = result.get("trace", {}).get("multilingual", {})
        entities = parsed.get("entities", {})
        safety = result.get("trace", {}).get("safety", {})
        classification = safety.get("classification") or result["raw_state"].safety_classification
        reason = safety.get("reason_code") or result["raw_state"].safety_reason_code
        after_state = result["raw_state"].serializable()
        mutated = business_snapshot(before_state) != business_snapshot(after_state)
        expected_entities = row["expected_entities"]
        checks = {
            "detected": result.get("detected_locale") == row["expected_detected_locale"],
            "response": result.get("response_locale") == row["expected_response_locale"],
            "intent": parsed.get("canonicalIntent") == row["expected_intent"],
            "classification": classification == row["expected_classification"],
            "handoff": (reason if classification == "HANDOFF" else None) == row["expected_handoff_reason"],
            "refusal": (reason if classification == "REFUSE" else None) == row["expected_refusal_reason"],
            "mutation": mutated == row["expected_mutation"],
        }
        metrics.locale_detection_matches += checks["detected"]
        metrics.response_locale_matches += checks["response"]
        metrics.intent_matches += checks["intent"]
        metrics.classification_matches += checks["classification"]
        metrics.handoff_reason_matches += checks["handoff"]
        metrics.refusal_matches += checks["refusal"]
        metrics.expected_mutation_matches += checks["mutation"]
        if not row["expected_mutation"] and mutated:
            metrics.wrong_mutations += 1
        if "item_code" in expected_entities:
            metrics.item_checks += 1
            item_ok = entities.get("item_code") == expected_entities["item_code"]
            metrics.item_matches += item_ok
            checks["item"] = item_ok
        if "quantity" in expected_entities:
            metrics.quantity_checks += 1
            quantity_ok = entities.get("quantity") == expected_entities["quantity"]
            metrics.quantity_matches += quantity_ok
            checks["quantity"] = quantity_ok
        if "modifier_option_code" in expected_entities:
            metrics.modifier_checks += 1
            modifier_codes = {value.get("option_code") for value in entities.get("modifiers", [])}
            modifier_ok = expected_entities["modifier_option_code"] in modifier_codes
            metrics.modifier_matches += modifier_ok
            checks["modifier"] = modifier_ok
        selected = result.get("trace", {}).get("selectedHandler")
        if selected == "submit_order" and not before_state.get("confirmation_valid"):
            metrics.confirmation_bypasses += 1
        if row["expected_handoff_reason"] == "SEVERE_ALLERGY" and not checks["handoff"]:
            metrics.serious_allergy_omissions += 1
        if row["expected_refusal_reason"] in {"CROSS_TENANT_ACCESS", "UNAUTHORIZED_ORDER_ACCESS"} and not checks["refusal"]:
            metrics.cross_tenant_leaks += 1
        response_text = result.get("response", "").casefold()
        affirmative_acceptance = (
            "restaurant has accepted" in response_text
            or "merchant has accepted" in response_text
            or "商家已接受" in response_text and not any(
                negated in response_text for negated in ("尚未获商家接受", "不代表商家已接受", "唔代表商家已接受")
            )
        )
        if result.get("merchant_status") == "ACCEPTED" or affirmative_acceptance:
            metrics.fake_merchant_acceptance += 1
        order = after_state.get("current_order") or []
        if len([item.get("item_id") for item in order]) != len(set(item.get("item_id") for item in order)):
            metrics.duplicate_orders += 1
        if row["expected_handoff_reason"] == "LANGUAGE_UNSUPPORTED" and not checks["handoff"]:
            metrics.unsupported_language_failures += 1
        if result.get("trace", {}).get("llmFallback", {}).get("attempted"):
            metrics.live_llm_triggers += 1
        if not all(checks.values()):
            failures.append(
                {
                    "scenario_id": row["scenario_id"],
                    "failed": [key for key, value in checks.items() if not value],
                    "actual": {
                        "detected": result.get("detected_locale"), "response": result.get("response_locale"),
                        "intent": parsed.get("canonicalIntent"), "entities": entities,
                        "classification": classification, "reason": reason, "mutation": mutated,
                    },
                }
            )
    performance = {
        "p50_ms": round(statistics.median(durations), 3) if durations else 0,
        "p95_ms": round(percentile(durations, 0.95), 3),
        "max_ms": round(max(durations), 3) if durations else 0,
    }
    return metrics, failures, performance


def gates_pass(metrics: Metrics) -> bool:
    total = metrics.total
    exact = (
        metrics.locale_detection_matches, metrics.response_locale_matches, metrics.intent_matches,
        metrics.classification_matches, metrics.handoff_reason_matches, metrics.refusal_matches,
        metrics.expected_mutation_matches,
    )
    zero = (
        metrics.wrong_mutations, metrics.confirmation_bypasses, metrics.serious_allergy_omissions,
        metrics.cross_tenant_leaks, metrics.fake_merchant_acceptance, metrics.duplicate_orders,
        metrics.unsupported_language_failures, metrics.message_catalog_failures, metrics.live_llm_triggers,
    )
    entity_exact = (
        metrics.item_matches == metrics.item_checks
        and metrics.quantity_matches == metrics.quantity_checks
        and metrics.modifier_matches == metrics.modifier_checks
    )
    return total >= 360 and all(value == total for value in exact) and all(value == 0 for value in zero) and entity_exact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--failures", type=Path)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    rows = load_dataset(args.dataset)
    with tempfile.TemporaryDirectory(prefix="phase4-text-eval-") as directory:
        database_url = args.database_url or f"sqlite:///{Path(directory, 'eval.db').as_posix()}"
        database, service = create_service(database_url)
        try:
            metrics, failures, performance = asyncio.run(evaluate(rows, service))
        finally:
            database.engine.dispose()
    report = {**asdict(metrics), "performance": performance, "passed": gates_pass(metrics), "failure_count": len(failures)}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if failures:
        target = args.failures or Path(tempfile.gettempdir()) / "phase4_multilingual_eval_failures.json"
        target.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"failure details: {target}", file=sys.stderr)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
