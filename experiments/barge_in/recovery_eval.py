from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from experiments.common.io import read_jsonl, write_csv, write_json
from experiments.common.metadata import ROOT, collect_metadata, sha256_file, sha256_paths
from experiments.common.offline import force_offline_environment


force_offline_environment("barge-in-recovery")
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.run_phase4_multilingual_text_eval import create_service, database_snapshot  # noqa: E402


PHASE4 = ROOT / "evaluation" / "phase4_multilingual_text.jsonl"
DEFINITION = ROOT / "experiments" / "barge_in" / "recovery_definition.json"
DEFAULT_RESULTS = ROOT / "experiments" / "results" / "barge_in"
DEFAULT_FIGURES = ROOT / "experiments" / "reports" / "figures" / "barge_in"
CONDITIONS = ("TP", "FP", "FN", "TN")


def _business_state(state: dict) -> dict:
    return {
        "current_order": state.get("current_order") or [],
        "fulfillment_type": state.get("fulfillment_type"),
        "official_delivery_address": state.get("official_delivery_address"),
        "phone": state.get("phone"),
        "lifecycle_status": state.get("lifecycle_status"),
        "merchant_status": state.get("merchant_status"),
        "submitted": bool(state.get("submitted")),
        "submitted_order_id": state.get("submitted_order_id"),
        "confirmation_valid": bool(state.get("confirmation_valid")),
        "safety_classification": state.get("safety_classification"),
    }


def _fingerprint(state: dict) -> str:
    return hashlib.sha256(json.dumps(_business_state(state), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _quantities(state: dict) -> list[int]:
    return [int(item.get("quantity", 0)) for item in state.get("current_order") or []]


def _mutated_only_as_requested(before: dict, after: dict, expected_quantity: int) -> bool:
    before_business = _business_state(before)
    after_business = _business_state(after)
    before_order = before_business.pop("current_order")
    after_order = after_business.pop("current_order")
    if before_business != after_business:
        return False
    if len(before_order) != 1 or len(after_order) != 1:
        return False
    before_line = dict(before_order[0])
    after_line = dict(after_order[0])
    before_line.pop("quantity", None)
    after_line.pop("quantity", None)
    return before_line == after_line and _quantities(after) == [expected_quantity]


def _source_pairs() -> dict[str, tuple[str, str]]:
    rows = read_jsonl(PHASE4)
    pairs = {}
    for locale in ("zh-CN", "yue-Hant-HK", "en-HK", "mixed"):
        row = next(
            item
            for item in rows
            if item["locale"] == locale and item["semantic_category"] == "change" and item["expression_variant"] == 1
        )
        if not row.get("setup_inputs"):
            raise ValueError(f"change scenario has no setup for {locale}")
        pairs[locale] = (row["setup_inputs"][0], row["input"])
    return pairs


async def evaluate(*, results_dir: Path, figures_dir: Path) -> dict:
    definition = json.loads(DEFINITION.read_text(encoding="utf-8"))
    if definition["cases_per_condition"] != 25:
        raise ValueError("recovery definition changed after preregistration")
    pairs = _source_pairs()
    locales = ("zh-CN", "yue-Hant-HK", "en-HK", "mixed")
    raw: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="order-barge-recovery-") as temp_dir:
        runtime = create_service(f"sqlite:///{Path(temp_dir, 'recovery.db').as_posix()}")
        try:
            for condition in CONDITIONS:
                for case_index in range(25):
                    locale = locales[case_index % len(locales)]
                    setup_text, correction_text = pairs[locale]
                    session_id = f"recovery-{condition}-{case_index + 1:02d}"
                    initial = await runtime.service.handle_text_message(
                        session_id,
                        setup_text,
                        restaurant_code="hk-sim-restaurant-a",
                        branch_code="central",
                        idempotency_key=f"recovery-{condition}-{case_index + 1}-setup",
                    )
                    before = initial["state"]
                    predicted_interruption = condition in {"TP", "FP"}
                    actual_interruption = condition in {"TP", "FN"}
                    correction_routed = condition in {"TP", "FN"}
                    if condition == "TP":
                        controller_action = "MARK_INTERRUPTED_AND_ROUTE_TEXT"
                    elif condition == "FP":
                        controller_action = "MARK_INTERRUPTED_REQUEST_CLARIFICATION_NO_TEXT_ROUTE"
                    elif condition == "FN":
                        controller_action = "KEEP_UNCONFIRMED_THEN_ROUTE_LATER_CORRECTION"
                    else:
                        controller_action = "CONTINUE_NO_MUTATION"

                    final_result = initial
                    if correction_routed:
                        final_result = await runtime.service.handle_text_message(
                            session_id,
                            correction_text,
                            restaurant_code="hk-sim-restaurant-a",
                            branch_code="central",
                            idempotency_key=f"recovery-{condition}-{case_index + 1}-correction",
                        )
                    after = final_result["state"]
                    expected_quantity = 3 if actual_interruption else 2
                    if condition in {"FP", "TN"}:
                        no_unintended_mutation = _fingerprint(before) == _fingerprint(after)
                    else:
                        no_unintended_mutation = _mutated_only_as_requested(before, after, expected_quantity)
                    correct_final_draft = len(after.get("current_order") or []) == 1 and _quantities(after) == [expected_quantity]
                    no_confirmation_bypass = not after.get("submitted") and not after.get("confirmation_valid")
                    database = database_snapshot(runtime, session_id)
                    no_duplicate_order = (
                        database["orders"] == 0
                        and database["duplicate_active_confirmations"] == 0
                        and database["duplicate_idempotency_records"] == 0
                    )
                    correct_safety_state = after.get("safety_classification") not in {"HANDOFF", "REFUSE"}
                    classifier_advisory = controller_action not in {"CONFIRM_ORDER", "SUBMIT_ORDER"}
                    checks = {
                        "no_unintended_mutation": no_unintended_mutation,
                        "correct_final_draft": correct_final_draft,
                        "no_confirmation_bypass": no_confirmation_bypass,
                        "no_duplicate_order": no_duplicate_order,
                        "correct_safety_state": correct_safety_state,
                        "classifier_is_advisory": classifier_advisory,
                    }
                    raw.append(
                        {
                            "case_id": session_id,
                            "condition": condition,
                            "locale": locale,
                            "predicted_interruption": predicted_interruption,
                            "actual_interruption": actual_interruption,
                            "correction_routed_via_text_entry": correction_routed,
                            "controller_action": controller_action,
                            "before_quantity": _quantities(before),
                            "expected_final_quantity": expected_quantity,
                            "actual_final_quantity": _quantities(after),
                            "before_state_sha256": _fingerprint(before),
                            "after_state_sha256": _fingerprint(after),
                            **checks,
                            "recovery_success": all(checks.values()),
                            "database_order_count": database["orders"],
                            "active_confirmation_count": database["active_confirmations"],
                            "duplicate_active_confirmations": database["duplicate_active_confirmations"],
                            "duplicate_idempotency_records": database["duplicate_idempotency_records"],
                            "final_safety_classification": after.get("safety_classification"),
                        }
                    )
        finally:
            runtime.database.engine.dispose()

    results_dir.mkdir(parents=True, exist_ok=True)
    raw_path = results_dir / "recovery_raw.csv"
    write_csv(raw_path, raw)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in raw:
        grouped[row["condition"]].append(row)
    by_condition = [
        {
            "condition": condition,
            "n": len(rows),
            "successes": sum(bool(row["recovery_success"]) for row in rows),
            "recovery_success_rate": sum(bool(row["recovery_success"]) for row in rows) / len(rows),
        }
        for condition, rows in sorted(grouped.items())
    ]
    failures = [row for row in raw if not row["recovery_success"]]
    analysis = {
        "experiment": "synthetic_state_machine_recovery",
        "definition_sha256": sha256_file(DEFINITION),
        "n": len(raw),
        "successes": len(raw) - len(failures),
        "recovery_success_rate": (len(raw) - len(failures)) / len(raw),
        "by_condition": by_condition,
        "failures": failures,
        "classifier_prediction_directly_confirmed_order": False,
        "production_barge_in_implemented": False,
        "qualifier": "synthetic dialogue-state recovery prototype",
    }
    write_json(results_dir / "recovery_analysis.json", analysis)
    write_csv(results_dir / "recovery_by_condition.csv", by_condition)
    write_json(
        results_dir / "recovery_metadata.json",
        collect_metadata(
            dataset_sha256=sha256_paths((PHASE4, DEFINITION)),
            random_seed=42,
            warmup_count=0,
            measurement_count=len(raw),
            provider_mode="offline_synthetic_recovery_sqlite",
            asr_provider="NOT_USED",
            tts_provider="NOT_USED",
            extra={
                "experiment": "synthetic_barge_in_recovery",
                "raw_csv_sha256": sha256_file(raw_path),
                "classifier_advisory_only": True,
                "production_code_modified": False,
            },
        ),
    )
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(evaluate(results_dir=args.results_dir, figures_dir=args.figures_dir)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
