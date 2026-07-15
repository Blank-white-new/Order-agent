from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPO_ROOT / "evaluation" / "phase1_scenarios.jsonl"
DEFAULT_SCHEMA = REPO_ROOT / "evaluation" / "phase1_scenarios.schema.json"
MIN_SCENARIOS = 120
MIN_PER_LOCALE = 30
VALID_CLASSIFICATIONS = {"AUTO_DRAFT", "CONFIRM", "HANDOFF", "REFUSE"}
FORBIDDEN_CLASSIFICATIONS = {
    "AUTO_SUBMIT",
    "AUTO_PAY",
    "AUTO_REFUND",
    "AUTO_GUARANTEE_ALLERGEN_SAFE",
}
REQUIRED_CATEGORIES = {
    "MENU_QUERY",
    "ORDER_MUTATION",
    "ORDER_REMOVAL_OR_UPDATE",
    "RECOMMENDATION",
    "FULFILLMENT_SELECTION",
    "ADDRESS_AND_PHONE",
    "FINAL_CONFIRMATION",
    "CUSTOMER_CHANGED_MIND",
    "REPEATED_CORRECTION",
    "AMBIGUOUS_ITEM",
    "AMBIGUOUS_QUANTITY",
    "PRICE_UNAVAILABLE",
    "SOLD_OUT",
    "OUTSIDE_HOURS",
    "LANGUAGE_SWITCH",
    "SEVERE_ALLERGY",
    "CROSS_CONTAMINATION",
    "INTOLERANCE",
    "COMPLAINT",
    "REFUND_REQUEST",
    "PAYMENT_DISPUTE",
    "EXPLICIT_HUMAN_REQUEST",
    "MERCHANT_TIMEOUT",
    "MERCHANT_REJECTED",
    "SYSTEM_FAILURE",
    "CALL_INTERRUPTION",
    "PROMPT_INJECTION",
    "UNAUTHORIZED_DATA_ACCESS",
    "OTHER_ORDER_ACCESS",
    "REPEATED_REQUEST",
    "ABUSE",
    "CONFIRMATION_BYPASS_OR_FAKE_ACCEPTANCE",
    "PAYMENT_CARD_DATA",
    "OUT_OF_SCOPE_SMS",
    "UNVERIFIABLE_FOOD_SAFETY_GUARANTEE",
}
HIGH_RISK_ALLERGY_CATEGORIES = {
    "SEVERE_ALLERGY",
    "CROSS_CONTAMINATION",
    "UNVERIFIABLE_FOOD_SAFETY_GUARANTEE",
}
PAYMENT_OR_REFUND_CATEGORIES = {"REFUND_REQUEST", "PAYMENT_DISPUTE", "PAYMENT_CARD_DATA"}
REFUSAL_CATEGORIES = {
    "PROMPT_INJECTION",
    "UNAUTHORIZED_DATA_ACCESS",
    "OTHER_ORDER_ACCESS",
    "ABUSE",
    "CONFIRMATION_BYPASS_OR_FAKE_ACCEPTANCE",
    "PAYMENT_CARD_DATA",
    "UNVERIFIABLE_FOOD_SAFETY_GUARANTEE",
}
ID_PATTERNS = {
    "scenario_id": re.compile(r"^P1-(?:ZH|YUE|EN|MIX)-\d{3}$"),
    "trace_id": re.compile(r"^SCENARIO-\d{3}$"),
    "requirement_ids": re.compile(r"^REQ-\d{3}$"),
    "risk_ids": re.compile(r"^RISK-\d{3}$"),
    "metric_ids": re.compile(r"^METRIC-\d{3}$"),
}
SECRET_PATTERNS = {
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
PHONE_PATTERNS = {
    "mainland mobile number": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "Hong Kong phone number": re.compile(r"(?<![\d+])(?:\+?852[- ]?)?[2-9]\d{7}(?!\d)"),
}
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    scenarios: list[dict[str, Any]]
    summary: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not self.errors


def _read_utf8(path: Path, errors: list[str]) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        errors.append(f"{path}: cannot read file: {exc}")
        return ""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{path}: file is not valid UTF-8: {exc}")
        return ""
    if text.startswith("\ufeff"):
        errors.append(f"{path}: UTF-8 BOM is not allowed")
    return text


def _load_schema(path: Path, errors: list[str]) -> dict[str, Any]:
    text = _read_utf8(path, errors)
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: schema is not valid JSON: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path}: schema root must be an object")
        return {}
    return value


def _load_jsonl(path: Path, errors: list[str]) -> list[dict[str, Any]]:
    text = _read_utf8(path, errors)
    if not text:
        return []
    scenarios: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            errors.append(f"{path}:{line_number}: blank lines are not allowed in JSONL")
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{line_number}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{path}:{line_number}: each JSONL value must be an object")
            continue
        value["__line__"] = line_number
        scenarios.append(value)
    return scenarios


def _document_ids(path: Path, prefix: str, errors: list[str]) -> set[str]:
    text = _read_utf8(path, errors)
    return set(re.findall(rf"\b{re.escape(prefix)}-\d{{3}}\b", text))


def _markdown_rows(path: Path, errors: list[str]) -> list[list[str]]:
    text = _read_utf8(path, errors)
    rows = []
    for line in text.splitlines():
        if line.startswith("| "):
            rows.append([part.strip() for part in line.strip().strip("|").split("|")])
    return rows


def _validate_types_and_schema(
    scenario: dict[str, Any],
    schema: dict[str, Any],
    errors: list[str],
) -> None:
    line = scenario.get("__line__", "?")
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    missing = [field for field in required if field not in scenario]
    if missing:
        errors.append(f"line {line}: missing required fields: {', '.join(missing)}")
    unknown = sorted(set(scenario) - set(properties) - {"__line__"})
    if schema.get("additionalProperties") is False and unknown:
        errors.append(f"line {line}: unknown fields: {', '.join(unknown)}")

    string_fields = {"scenario_id", "trace_id", "title", "market", "locale", "category", "user_input", "notes"}
    list_fields = {
        "preconditions",
        "requirement_ids",
        "risk_ids",
        "metric_ids",
        "data_classes",
        "forbidden_outcomes",
    }
    for field in string_fields:
        if field in scenario and (not isinstance(scenario[field], str) or not scenario[field].strip()):
            errors.append(f"line {line}: {field} must be a non-empty string")
    for field in list_fields:
        value = scenario.get(field)
        if value is not None and (
            not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            errors.append(f"line {line}: {field} must be an array of non-empty strings")
    if "required_confirmation" in scenario and not isinstance(scenario["required_confirmation"], bool):
        errors.append(f"line {line}: required_confirmation must be boolean")
    if "future_stage" in scenario and (
        not isinstance(scenario["future_stage"], int) or isinstance(scenario["future_stage"], bool) or not 2 <= scenario["future_stage"] <= 12
    ):
        errors.append(f"line {line}: future_stage must be an integer from 2 through 12")
    reason = scenario.get("handoff_reason_code")
    if reason is not None and not isinstance(reason, str):
        errors.append(f"line {line}: handoff_reason_code must be a string or null")


def _validate_scenario_rules(
    scenario: dict[str, Any],
    *,
    schema: dict[str, Any],
    requirement_ids: set[str],
    risk_ids: set[str],
    metric_ids: set[str],
    errors: list[str],
) -> None:
    line = scenario.get("__line__", "?")
    scenario_id = scenario.get("scenario_id", f"line {line}")
    classification = scenario.get("expected_classification")
    category = scenario.get("category")

    for field, pattern in ID_PATTERNS.items():
        values = scenario.get(field)
        values = values if isinstance(values, list) else [values]
        for value in values:
            if isinstance(value, str) and not pattern.fullmatch(value):
                errors.append(f"{scenario_id}: invalid {field} value {value!r}")

    allowed_locales = set(schema.get("properties", {}).get("locale", {}).get("enum", []))
    allowed_categories = set(schema.get("properties", {}).get("category", {}).get("enum", []))
    allowed_data_classes = set(schema.get("properties", {}).get("data_classes", {}).get("items", {}).get("enum", []))
    allowed_reasons = set(schema.get("properties", {}).get("handoff_reason_code", {}).get("enum", []))
    if scenario.get("market") != "HK_SIMULATION":
        errors.append(f"{scenario_id}: market must be HK_SIMULATION")
    if scenario.get("locale") not in allowed_locales:
        errors.append(f"{scenario_id}: invalid locale {scenario.get('locale')!r}")
    if category not in allowed_categories:
        errors.append(f"{scenario_id}: invalid category {category!r}")
    if classification not in VALID_CLASSIFICATIONS:
        errors.append(f"{scenario_id}: invalid expected_classification {classification!r}")
    if classification in FORBIDDEN_CLASSIFICATIONS:
        errors.append(f"{scenario_id}: forbidden classification {classification}")

    reason = scenario.get("handoff_reason_code")
    if classification == "HANDOFF":
        if not reason or reason not in allowed_reasons:
            errors.append(f"{scenario_id}: HANDOFF requires a valid handoff_reason_code")
    elif reason is not None:
        errors.append(f"{scenario_id}: non-HANDOFF scenario must have null handoff_reason_code")

    required_confirmation = scenario.get("required_confirmation")
    if classification == "CONFIRM" and required_confirmation is not True:
        errors.append(f"{scenario_id}: CONFIRM requires required_confirmation=true")
    if classification != "CONFIRM" and required_confirmation is not False:
        errors.append(f"{scenario_id}: only CONFIRM may set required_confirmation=true")

    if category in HIGH_RISK_ALLERGY_CATEGORIES and classification == "AUTO_DRAFT":
        errors.append(f"{scenario_id}: high-risk allergy scenario cannot be AUTO_DRAFT")
    if category in {"SEVERE_ALLERGY", "CROSS_CONTAMINATION"} and classification != "HANDOFF":
        errors.append(f"{scenario_id}: {category} must be HANDOFF")
    if category == "UNVERIFIABLE_FOOD_SAFETY_GUARANTEE" and classification != "REFUSE":
        errors.append(f"{scenario_id}: unverified food-safety guarantee must be REFUSE")
    if category in PAYMENT_OR_REFUND_CATEGORIES and classification == "AUTO_DRAFT":
        errors.append(f"{scenario_id}: payment/refund scenario cannot be AUTO_DRAFT")
    if category == "EXPLICIT_HUMAN_REQUEST" and (
        classification != "HANDOFF" or reason != "EXPLICIT_HUMAN_REQUEST"
    ):
        errors.append(f"{scenario_id}: explicit human request must HANDOFF with its exact reason code")
    if category == "OTHER_ORDER_ACCESS" and classification != "REFUSE":
        errors.append(f"{scenario_id}: request to view another order must be REFUSE")
    if category == "FINAL_CONFIRMATION" and classification != "CONFIRM":
        errors.append(f"{scenario_id}: final submission must be at least CONFIRM")
    if category == "MERCHANT_TIMEOUT":
        forbidden = scenario.get("forbidden_outcomes", [])
        if "merchant_accepted" not in forbidden or classification == "AUTO_DRAFT":
            errors.append(f"{scenario_id}: merchant timeout must forbid merchant_accepted")
    if category in REFUSAL_CATEGORIES and classification != "REFUSE":
        errors.append(f"{scenario_id}: refusal rule category {category} must be REFUSE")

    req_refs = scenario.get("requirement_ids", []) if isinstance(scenario.get("requirement_ids"), list) else []
    risk_refs = scenario.get("risk_ids", []) if isinstance(scenario.get("risk_ids"), list) else []
    metric_refs = scenario.get("metric_ids", []) if isinstance(scenario.get("metric_ids"), list) else []
    if not (req_refs or risk_refs or metric_refs):
        errors.append(f"{scenario_id}: must reference at least one requirement, risk, or metric")
    for value, known, field in (
        (req_refs, requirement_ids, "requirement_ids"),
        (risk_refs, risk_ids, "risk_ids"),
        (metric_refs, metric_ids, "metric_ids"),
    ):
        for reference in value:
            if reference not in known:
                errors.append(f"{scenario_id}: unknown {field} reference {reference}")
        if len(value) != len(set(value)):
            errors.append(f"{scenario_id}: duplicate value in {field}")

    for data_class in scenario.get("data_classes", []) if isinstance(scenario.get("data_classes"), list) else []:
        if data_class not in allowed_data_classes:
            errors.append(f"{scenario_id}: invalid data class {data_class}")
    forbidden = scenario.get("forbidden_outcomes", [])
    if not isinstance(forbidden, list) or not forbidden:
        errors.append(f"{scenario_id}: forbidden_outcomes must not be empty")
    elif len(forbidden) != len(set(forbidden)):
        errors.append(f"{scenario_id}: duplicate forbidden_outcomes")


def _validate_sensitive_content(scenarios: list[dict[str, Any]], errors: list[str]) -> None:
    for scenario in scenarios:
        scenario_id = scenario.get("scenario_id", f"line {scenario.get('__line__', '?')}")
        text = json.dumps({key: value for key, value in scenario.items() if key != "__line__"}, ensure_ascii=False)
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{scenario_id}: contains a possible real {label}")
        for label, pattern in PHONE_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{scenario_id}: contains a possible real {label}; use an obvious TEST placeholder")
        if EMAIL_PATTERN.search(text):
            errors.append(f"{scenario_id}: contains a possible real email address")


def _validate_catalog_coverage(
    scenarios: list[dict[str, Any]],
    *,
    schema: dict[str, Any],
    risk_rows: list[list[str]],
    metric_rows: list[list[str]],
    requirement_ids: set[str],
    errors: list[str],
) -> dict[str, Any]:
    scenario_ids = [scenario.get("scenario_id") for scenario in scenarios]
    trace_ids = [scenario.get("trace_id") for scenario in scenarios]
    titles = [scenario.get("title") for scenario in scenarios]
    inputs = [scenario.get("user_input") for scenario in scenarios]
    for label, values in (
        ("scenario_id", scenario_ids),
        ("trace_id", trace_ids),
        ("title", titles),
        ("user_input", inputs),
    ):
        duplicates = sorted(value for value, count in Counter(values).items() if value is not None and count > 1)
        if duplicates:
            errors.append(f"duplicate {label} values: {', '.join(map(str, duplicates[:5]))}")

    if len(scenarios) < MIN_SCENARIOS:
        errors.append(f"catalog has {len(scenarios)} scenarios; minimum is {MIN_SCENARIOS}")
    locale_counts = Counter(scenario.get("locale") for scenario in scenarios)
    for locale in schema.get("properties", {}).get("locale", {}).get("enum", []):
        if locale_counts[locale] < MIN_PER_LOCALE:
            errors.append(f"locale {locale} has {locale_counts[locale]} scenarios; minimum is {MIN_PER_LOCALE}")
    category_counts = Counter(scenario.get("category") for scenario in scenarios)
    missing_categories = sorted(REQUIRED_CATEGORIES - set(category_counts))
    if missing_categories:
        errors.append(f"missing required categories: {', '.join(missing_categories)}")

    used_reasons = {
        scenario.get("handoff_reason_code")
        for scenario in scenarios
        if scenario.get("expected_classification") == "HANDOFF"
    }
    required_reasons = set(schema.get("properties", {}).get("handoff_reason_code", {}).get("enum", [])) - {None}
    missing_reasons = sorted(required_reasons - used_reasons)
    if missing_reasons:
        errors.append(f"handoff reason codes without a scenario: {', '.join(missing_reasons)}")

    used_requirements = {value for scenario in scenarios for value in scenario.get("requirement_ids", [])}
    missing_requirements = sorted(requirement_ids - used_requirements)
    if missing_requirements:
        errors.append(f"requirements without a catalog scenario: {', '.join(missing_requirements)}")
    used_risks = {value for scenario in scenarios for value in scenario.get("risk_ids", [])}
    used_metrics = {value for scenario in scenarios for value in scenario.get("metric_ids", [])}
    high_risks = {
        row[0]
        for row in risk_rows
        if len(row) == 12 and row[0].startswith("RISK-") and row[6] in {"HIGH", "CRITICAL"}
    }
    missing_high_risks = sorted(high_risks - used_risks)
    if missing_high_risks:
        errors.append(f"high-severity risks without a catalog scenario: {', '.join(missing_high_risks)}")
    blocking_metrics = {
        row[0]
        for row in metric_rows
        if len(row) == 7 and row[0].startswith("METRIC-") and row[5] == "BLOCKER"
    }
    missing_blockers = sorted(blocking_metrics - used_metrics)
    if missing_blockers:
        errors.append(f"blocking metrics without a catalog scenario: {', '.join(missing_blockers)}")

    expected_trace_ids = [f"SCENARIO-{index:03d}" for index in range(1, len(scenarios) + 1)]
    if trace_ids != expected_trace_ids:
        errors.append("trace_id values must be contiguous and ordered from SCENARIO-001")

    return {
        "total": len(scenarios),
        "locales": dict(sorted(locale_counts.items())),
        "classifications": dict(sorted(Counter(scenario.get("expected_classification") for scenario in scenarios).items())),
        "categories": dict(sorted(category_counts.items())),
        "requirements_referenced": len(used_requirements),
        "requirements_isolated": len(missing_requirements),
        "risks_referenced": len(used_risks),
        "metrics_referenced": len(used_metrics),
        "high_risk_isolated": len(missing_high_risks),
        "blocking_metrics_isolated": len(missing_blockers),
    }


def _validate_risk_trace_rows(
    rows: list[list[str]],
    *,
    scenario_trace_ids: set[str],
    metric_ids: set[str],
    errors: list[str],
) -> None:
    controls = {row[0]: row for row in rows if len(row) == 6 and row[0].startswith("RISK-")}
    core = {row[0]: row for row in rows if len(row) == 12 and row[0].startswith("RISK-")}
    for risk_id, row in core.items():
        if row[6] not in {"HIGH", "CRITICAL"}:
            continue
        control = controls.get(risk_id)
        if not control:
            errors.append(f"{risk_id}: high-severity risk has no control/trace row")
            continue
        if any(not value.strip() for value in control[1:4]):
            errors.append(f"{risk_id}: high-severity risk must have preventive, detective and fallback controls")
        related_metrics = set(re.findall(r"METRIC-\d{3}", control[4]))
        related_scenarios = set(re.findall(r"SCENARIO-\d{3}", control[5]))
        if not related_metrics or not related_metrics <= metric_ids:
            errors.append(f"{risk_id}: high-severity risk has invalid related_metrics")
        if not related_scenarios or not related_scenarios <= scenario_trace_ids:
            errors.append(f"{risk_id}: high-severity risk has invalid related_scenarios")
        try:
            stage = int(row[10])
        except ValueError:
            stage = 0
        if not 2 <= stage <= 12:
            errors.append(f"{risk_id}: high-severity risk has invalid future_stage")


def validate_catalog(
    catalog_path: str | Path = DEFAULT_CATALOG,
    schema_path: str | Path = DEFAULT_SCHEMA,
    repo_root: str | Path = REPO_ROOT,
) -> ValidationResult:
    errors: list[str] = []
    root = Path(repo_root)
    schema = _load_schema(Path(schema_path), errors)
    scenarios = _load_jsonl(Path(catalog_path), errors)
    requirement_ids = _document_ids(root / "docs" / "phase-1" / "product-scope.md", "REQ", errors)
    risk_ids = _document_ids(root / "docs" / "phase-1" / "risk-register.md", "RISK", errors)
    metric_ids = _document_ids(root / "docs" / "phase-1" / "acceptance-metrics.md", "METRIC", errors)
    risk_rows = _markdown_rows(root / "docs" / "phase-1" / "risk-register.md", errors)
    metric_rows = _markdown_rows(root / "docs" / "phase-1" / "acceptance-metrics.md", errors)

    if schema:
        for scenario in scenarios:
            _validate_types_and_schema(scenario, schema, errors)
            _validate_scenario_rules(
                scenario,
                schema=schema,
                requirement_ids=requirement_ids,
                risk_ids=risk_ids,
                metric_ids=metric_ids,
                errors=errors,
            )
    _validate_sensitive_content(scenarios, errors)
    summary = _validate_catalog_coverage(
        scenarios,
        schema=schema,
        risk_rows=risk_rows,
        metric_rows=metric_rows,
        requirement_ids=requirement_ids,
        errors=errors,
    )
    _validate_risk_trace_rows(
        risk_rows,
        scenario_trace_ids={scenario.get("trace_id") for scenario in scenarios if isinstance(scenario.get("trace_id"), str)},
        metric_ids=metric_ids,
        errors=errors,
    )
    cleaned = [{key: value for key, value in scenario.items() if key != "__line__"} for scenario in scenarios]
    return ValidationResult(errors=errors, scenarios=cleaned, summary=summary)


def main() -> int:
    result = validate_catalog()
    if result.errors:
        print(f"Phase 1 scenario validation failed with {len(result.errors)} error(s):", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Phase 1 scenario catalog validation passed.")
    print(json.dumps(result.summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
