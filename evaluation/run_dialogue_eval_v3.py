from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import tempfile
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
DEFAULT_DATASET = Path(__file__).with_name("dialogues_v3.jsonl")

LLM_CONNECTION_ENV_VARS = (
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
VALID_CATEGORIES = {
    "normal_order",
    "modify_order",
    "recommendation",
    "delivery",
    "confirmation",
    "asr_noise",
    "multi_intent",
    "ambiguous_reference",
    "should_clarify",
    "should_reject",
}
VALID_EXPECTED_RESULT_TYPES = {
    "should_pass",
    "should_clarify",
    "should_reject",
    "should_not_mutate",
}
TRACKED_STATE_FIELDS = (
    "stage",
    "current_order",
    "fulfillment_type",
    "official_delivery_address",
    "pending_delivery_address_candidate",
    "pending_action",
    "phone",
    "submitted",
    "submitted_order_id",
)
CLARIFICATION_MARKERS = ("没太理解", "请明确", "请具体", "具体是", "哪一", "哪个", "请说", "需要什么")
REJECTION_MARKERS = ("不能", "不支持", "不允许", "无法", "菜单里没", "必须确认", "不能跳过确认")


class DatasetValidationError(ValueError):
    """Raised when the JSONL contract is invalid."""


def force_offline_environment() -> Path:
    """Disable live LLM configuration before importing application modules."""
    os.environ["LLM_FALLBACK_MODE"] = "disabled"
    os.environ["LLM_FALLBACK_ENABLED"] = "false"
    os.environ["LLM_FALLBACK_SPECULATIVE_ENABLED"] = "false"
    os.environ["ALLOW_LIVE_LLM"] = "false"
    for name in LLM_CONNECTION_ENV_VARS:
        os.environ.pop(name, None)
    offline_env_file = Path(tempfile.gettempdir()) / (
        f"agent-order-eval-v3-offline-{os.getpid()}-{uuid.uuid4().hex}.env"
    )
    os.environ["BACKEND_ENV_FILE"] = str(offline_env_file)
    return offline_env_file


# This must happen before the application can construct its module-level LLM client.
force_offline_environment()
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.orchestrator import OrchestratorAgent  # noqa: E402
from app.services import llm_client as llm_module  # noqa: E402
from app.services.llm_replay_client import (  # noqa: E402
    InMemoryFakeLLMClient,
    ReplayLLMClient,
    ShadowLLMClient,
)
from app.services.text_entry_service import TextEntryService  # noqa: E402
from app.state.session_store import InMemorySessionStore  # noqa: E402


class OfflineOnlyLLMClient:
    """A hard stop behind the environment guard: network interpretation is impossible."""

    timeout_seconds = 0.0
    top_candidates = 8
    speculative_enabled = False
    runtime_mode = "disabled"
    is_shadow = False
    network_allowed = False

    def is_enabled(self) -> bool:
        return False

    def is_configured(self) -> bool:
        return False

    def can_call(self) -> bool:
        return False

    def interpret(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("V3 evaluation forbids live LLM calls")


def create_text_entry_service(
    llm_mode: str = "disabled", replay_file: str | Path | None = None
) -> TextEntryService:
    force_offline_environment()
    llm_module._env_file_values.cache_clear()
    orchestrator = OrchestratorAgent()
    if llm_mode == "disabled":
        orchestrator.llm_client = OfflineOnlyLLMClient()
    elif llm_mode == "fake":
        orchestrator.llm_client = InMemoryFakeLLMClient()
    elif llm_mode == "replay":
        orchestrator.llm_client = ReplayLLMClient(replay_file)
    elif llm_mode == "shadow":
        source = ReplayLLMClient(replay_file) if replay_file else InMemoryFakeLLMClient()
        orchestrator.llm_client = ShadowLLMClient(source)
    else:
        raise ValueError(f"unsupported offline LLM mode: {llm_mode}")
    return TextEntryService(store=InMemorySessionStore(), orchestrator=orchestrator)


def load_dataset(path: str | Path) -> list[dict[str, Any]]:
    dataset_path = Path(path)
    samples: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    try:
        lines = dataset_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise DatasetValidationError(f"无法读取数据集 {dataset_path}: {exc}") from exc

    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            sample = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise DatasetValidationError(f"第 {line_number} 行不是有效 JSON: {exc.msg}") from exc
        _validate_sample(sample, line_number)
        sample_id = sample["id"]
        if sample_id in seen_ids:
            raise DatasetValidationError(f"第 {line_number} 行样本 ID 重复: {sample_id}")
        seen_ids.add(sample_id)
        samples.append(sample)
    if not samples:
        raise DatasetValidationError("数据集不能为空")
    return samples


def _validate_sample(sample: Any, line_number: int) -> None:
    prefix = f"第 {line_number} 行"
    if not isinstance(sample, dict):
        raise DatasetValidationError(f"{prefix}必须是 JSON object")
    for field in ("id", "category", "expected_result_type", "turns", "expected"):
        if field not in sample:
            raise DatasetValidationError(f"{prefix}缺少字段: {field}")
    if not isinstance(sample["id"], str) or not sample["id"].strip():
        raise DatasetValidationError(f"{prefix}的 id 必须是非空字符串")
    if sample["category"] not in VALID_CATEGORIES:
        raise DatasetValidationError(f"{prefix}包含非法 category: {sample['category']}")
    if sample["expected_result_type"] not in VALID_EXPECTED_RESULT_TYPES:
        raise DatasetValidationError(
            f"{prefix}包含非法 expected_result_type: {sample['expected_result_type']}"
        )
    if not isinstance(sample["turns"], list) or not sample["turns"]:
        raise DatasetValidationError(f"{prefix}的 turns 必须是非空数组")
    for turn_index, turn in enumerate(sample["turns"], start=1):
        if not isinstance(turn, dict) or not isinstance(turn.get("user"), str) or not turn["user"].strip():
            raise DatasetValidationError(f"{prefix}第 {turn_index} 个 turn 缺少非空 user")
        if "evaluate" in turn and not isinstance(turn["evaluate"], bool):
            raise DatasetValidationError(f"{prefix}第 {turn_index} 个 turn 的 evaluate 必须是布尔值")
    expected = sample["expected"]
    if not isinstance(expected, dict):
        raise DatasetValidationError(f"{prefix}的 expected 必须是 object")
    for field in ("should_mutate_order", "allow_order_mutation", "should_clarify", "should_reject"):
        if field not in expected or not isinstance(expected[field], bool):
            raise DatasetValidationError(f"{prefix}的 expected.{field} 必须是布尔值")
    if "items" in expected and not isinstance(expected["items"], list):
        raise DatasetValidationError(f"{prefix}的 expected.items 必须是数组")


def filter_samples(
    samples: Iterable[dict[str, Any]],
    *,
    category: str | None = None,
    expected_result_type: str | None = None,
    max_dialogues: int | None = None,
) -> list[dict[str, Any]]:
    selected = [
        sample
        for sample in samples
        if (category is None or sample["category"] == category)
        and (expected_result_type is None or sample["expected_result_type"] == expected_result_type)
    ]
    return selected[:max_dialogues] if max_dialogues is not None else selected


async def evaluate_sample(
    sample: dict[str, Any],
    service_factory: Callable[[], TextEntryService] = create_text_entry_service,
) -> dict[str, Any]:
    service = service_factory()
    session_id = f"eval-v3-{sample['id']}-{uuid.uuid4().hex}"
    turns: list[dict[str, Any]] = []
    confirmation_bypass_count = 0

    for turn_number, turn in enumerate(sample["turns"], start=1):
        before = copy.deepcopy(service.store.get(session_id).serializable())
        result = await service.handle_text_message(session_id, turn["user"])
        after = copy.deepcopy(result["state"])
        trace = copy.deepcopy(result.get("trace", {}))
        response = str(result.get("response", ""))
        order_mutated = before.get("current_order") != after.get("current_order")
        state_diff = _state_diff(before, after)
        submitted_now = not bool(before.get("submitted")) and bool(after.get("submitted"))
        confirmation_bypass = submitted_now and trace.get("finalIntent") != "confirm"
        confirmation_bypass_count += int(confirmation_bypass)
        turns.append(
            {
                "turn": turn_number,
                "evaluate": turn.get("evaluate", True),
                "user_input": turn["user"],
                "assistant_reply": response,
                "intent": trace.get("finalIntent"),
                "route": {
                    "agent": trace.get("selectedAgent"),
                    "handler": trace.get("selectedHandler"),
                    "source": trace.get("interpretationSource"),
                },
                "trace": trace,
                "order_state_before": before.get("current_order", []),
                "order_state_after": after.get("current_order", []),
                "state_before": before,
                "state_after": after,
                "state_diff": state_diff,
                "order_mutated": order_mutated,
                "clarified": _is_clarification(response, trace, after),
                "rejected": _is_rejection(response, trace),
                "fallback": bool(trace.get("fallbackUsed")),
                "confirmation_bypass": confirmation_bypass,
            }
        )

    checked_turns = [turn for turn in turns if turn["evaluate"]]
    final_state = turns[-1]["state_after"]
    actual = {
        "items": _compact_items(final_state.get("current_order", [])),
        "stage": final_state.get("stage"),
        "fulfillment_type": final_state.get("fulfillment_type"),
        "official_delivery_address": final_state.get("official_delivery_address"),
        "phone": final_state.get("phone"),
        "submitted": bool(final_state.get("submitted")),
        "submitted_order_id": final_state.get("submitted_order_id"),
        "submitted_order_id_changed": any(
            turn["state_before"].get("submitted_order_id")
            != turn["state_after"].get("submitted_order_id")
            for turn in checked_turns
        ),
        "should_mutate_order": any(turn["order_mutated"] for turn in checked_turns),
        "clarified": any(turn["clarified"] for turn in checked_turns),
        "rejected": any(turn["rejected"] for turn in checked_turns),
        "fallback_count": sum(int(turn["fallback"]) for turn in checked_turns),
        "confirmation_bypass_count": confirmation_bypass_count,
        "final_intent": checked_turns[-1]["intent"] if checked_turns else turns[-1]["intent"],
        "lifecycle_reason": (
            checked_turns[-1]["trace"].get("lifecycleReason")
            if checked_turns
            else turns[-1]["trace"].get("lifecycleReason")
        ),
    }
    reasons = _compare_expected(sample["expected"], actual, checked_turns)
    return {
        "id": sample["id"],
        "category": sample["category"],
        "expected_result_type": sample["expected_result_type"],
        "passed": not reasons,
        "expected": sample["expected"],
        "actual": actual,
        "turns": turns,
        "state_diff_summary": _summarize_diffs(checked_turns),
        "failure_reasons": reasons,
        "notes": sample.get("notes", ""),
        "false_mutation_count": sum(
            int(turn["order_mutated"])
            for turn in checked_turns
            if not sample["expected"]["allow_order_mutation"]
        ),
        "confirmation_bypass_count": confirmation_bypass_count,
        "fallback_count": actual["fallback_count"],
    }


async def evaluate_samples(
    samples: Iterable[dict[str, Any]],
    *,
    verbose: bool = False,
    service_factory: Callable[[], TextEntryService] = create_text_entry_service,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for sample in samples:
        try:
            result = await evaluate_sample(sample, service_factory=service_factory)
        except Exception as exc:  # A broken dialogue is reported; the suite keeps running.
            result = {
                "id": sample["id"],
                "category": sample["category"],
                "expected_result_type": sample["expected_result_type"],
                "passed": False,
                "expected": sample["expected"],
                "actual": {"runtime_error": f"{type(exc).__name__}: {exc}"},
                "turns": [],
                "state_diff_summary": "无（样本运行异常）",
                "failure_reasons": [f"样本运行异常: {type(exc).__name__}: {exc}"],
                "notes": sample.get("notes", ""),
                "false_mutation_count": 0,
                "confirmation_bypass_count": 0,
                "fallback_count": 0,
            }
        results.append(result)
        if verbose:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"[{status}] {result['id']} ({result['category']})")
    return results


def _compact_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": item.get("name"),
            "quantity": item.get("quantity", 1),
            "options": item.get("options", []),
        }
        for item in items
    ]


def _state_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        field: {"before": before.get(field), "after": after.get(field)}
        for field in TRACKED_STATE_FIELDS
        if before.get(field) != after.get(field)
    }


def _is_clarification(response: str, trace: dict[str, Any], state: dict[str, Any]) -> bool:
    return bool(
        trace.get("fallbackUsed")
        or state.get("pending_question")
        or any(marker in response for marker in CLARIFICATION_MARKERS)
    )


def _is_rejection(response: str, trace: dict[str, Any]) -> bool:
    return bool(trace.get("stateMutationRejectedReason") or any(marker in response for marker in REJECTION_MARKERS))


def _compare_expected(
    expected: dict[str, Any], actual: dict[str, Any], checked_turns: list[dict[str, Any]]
) -> list[str]:
    reasons: list[str] = []
    if actual["should_mutate_order"] != expected["should_mutate_order"]:
        reasons.append(
            f"订单 mutation 预期={expected['should_mutate_order']}，实际={actual['should_mutate_order']}"
        )
    if not expected["allow_order_mutation"] and actual["should_mutate_order"]:
        reasons.append("不允许修改订单的评估轮发生了订单 mutation")
    if actual["clarified"] != expected["should_clarify"]:
        reasons.append(f"澄清预期={expected['should_clarify']}，实际={actual['clarified']}")
    if actual["rejected"] != expected["should_reject"]:
        reasons.append(f"拒绝预期={expected['should_reject']}，实际={actual['rejected']}")

    if "items" in expected:
        expected_items = expected["items"]
        if not _items_match(expected_items, actual["items"], exact=expected.get("exact_items", True)):
            reasons.append(f"订单预期={expected_items}，实际={actual['items']}")
    for field in (
        "stage",
        "fulfillment_type",
        "official_delivery_address",
        "phone",
        "submitted",
        "submitted_order_id",
        "submitted_order_id_changed",
        "lifecycle_reason",
    ):
        if field in expected and actual.get(field) != expected[field]:
            reasons.append(f"{field} 预期={expected[field]!r}，实际={actual.get(field)!r}")
    if "final_intent" in expected:
        allowed = expected["final_intent"]
        allowed = [allowed] if isinstance(allowed, str) else allowed
        if actual["final_intent"] not in allowed:
            reasons.append(f"final_intent 预期属于={allowed}，实际={actual['final_intent']!r}")
    if actual["confirmation_bypass_count"]:
        reasons.append(f"检测到 {actual['confirmation_bypass_count']} 次绕过确认提交")
    if not checked_turns:
        reasons.append("样本没有 evaluate=true 的评估轮")
    return reasons


def _items_match(expected: list[dict[str, Any]], actual: list[dict[str, Any]], *, exact: bool) -> bool:
    if exact and len(expected) != len(actual):
        return False
    unmatched = list(actual)
    for expected_item in expected:
        match_index = next(
            (
                index
                for index, actual_item in enumerate(unmatched)
                if actual_item.get("name") == expected_item.get("name")
                and actual_item.get("quantity", 1) == expected_item.get("quantity", 1)
                and all(option in actual_item.get("options", []) for option in expected_item.get("options", []))
            ),
            None,
        )
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return True


def _summarize_diffs(turns: list[dict[str, Any]]) -> str:
    summaries = []
    for turn in turns:
        fields = ", ".join(turn["state_diff"].keys()) or "无受评估状态变化"
        summaries.append(f"turn {turn['turn']}: {fields}")
    return "; ".join(summaries)


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(int(result["passed"]) for result in results)
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    by_result_type: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        status = "passed" if result["passed"] else "failed"
        by_category[result["category"]][status] += 1
        by_result_type[result["expected_result_type"]][status] += 1
    traces = [
        turn.get("trace", {})
        for result in results
        for turn in result.get("turns", [])
        if turn.get("evaluate", True)
    ]
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round((passed / total * 100) if total else 0.0, 2),
        "by_category": {name: dict(counts) for name, counts in sorted(by_category.items())},
        "by_expected_result_type": {
            name: dict(counts) for name, counts in sorted(by_result_type.items())
        },
        "false_mutation_count": sum(result["false_mutation_count"] for result in results),
        "confirmation_bypass_count": sum(result["confirmation_bypass_count"] for result in results),
        "fallback_count": sum(result["fallback_count"] for result in results),
        "llm_trigger_count": sum(int(bool(trace.get("llmFallbackTriggered"))) for trace in traces),
        "llm_shadow_candidate_count": sum(int(bool(trace.get("llmFallbackShadowCandidate"))) for trace in traces),
        "llm_validation_accept_count": sum(int(bool(trace.get("llmFallbackValidationAccepted"))) for trace in traces),
        "llm_validation_reject_count": sum(int(bool(trace.get("llmFallbackValidationRejected"))) for trace in traces),
        "llm_would_mutate_count": sum(int(bool(trace.get("llmFallbackWouldMutateOrder"))) for trace in traces),
    }


def print_report(results: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    print("\n=== V3 对话评估汇总（强制离线）===")
    print(f"总数: {summary['total']}")
    print(f"passed: {summary['passed']}")
    print(f"failed: {summary['failed']}")
    print(f"pass rate: {summary['pass_rate']:.2f}%")
    print(f"false mutation count: {summary['false_mutation_count']}")
    print(f"confirmation bypass count: {summary['confirmation_bypass_count']}")
    print(f"fallback count: {summary['fallback_count']}")
    print(f"llm trigger count: {summary['llm_trigger_count']}")
    print(f"llm shadow candidate count: {summary['llm_shadow_candidate_count']}")
    print(f"llm validation accept count: {summary['llm_validation_accept_count']}")
    print(f"llm validation reject count: {summary['llm_validation_reject_count']}")
    print(f"llm would mutate count: {summary['llm_would_mutate_count']}")
    _print_group("按 category", summary["by_category"])
    _print_group("按 expected_result_type", summary["by_expected_result_type"])

    failures = [result for result in results if not result["passed"]]
    if failures:
        print("\n=== 失败样本 ===")
    for result in failures:
        user_inputs = [turn["user_input"] for turn in result["turns"] if turn.get("evaluate", True)]
        print(f"\n- sample id: {result['id']}")
        print(f"  category: {result['category']}")
        print(f"  expected_result_type: {result['expected_result_type']}")
        print(f"  用户输入: {json.dumps(user_inputs, ensure_ascii=False)}")
        print(f"  预期: {json.dumps(result['expected'], ensure_ascii=False, sort_keys=True)}")
        print(f"  实际: {json.dumps(result['actual'], ensure_ascii=False, sort_keys=True)}")
        print(f"  状态 diff 摘要: {result['state_diff_summary']}")
        print(f"  失败原因: {'; '.join(result['failure_reasons'])}")


def _print_group(title: str, grouped: dict[str, dict[str, int]]) -> None:
    print(f"{title}:")
    for name, counts in grouped.items():
        passed = counts.get("passed", 0)
        failed = counts.get("failed", 0)
        print(f"  {name}: total={passed + failed}, passed={passed}, failed={failed}")


def write_json_report(path: str | Path, results: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行默认强制离线的 V3 对话评估")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="V3 JSONL 数据集路径")
    parser.add_argument("--max-dialogues", type=int, help="最多运行多少条样本")
    parser.add_argument("--category", choices=sorted(VALID_CATEGORIES))
    parser.add_argument("--expected-result-type", choices=sorted(VALID_EXPECTED_RESULT_TYPES))
    parser.add_argument("--fail-on-regression", action="store_true", help="存在失败样本时返回退出码 1")
    parser.add_argument("--json-report", help="可选 JSON 报告输出路径")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--llm-mode",
        choices=("disabled", "fake", "replay", "shadow"),
        default="disabled",
        help="离线 LLM sandbox 模式；不提供 live",
    )
    parser.add_argument("--llm-replay-file", help="replay 或 replay-backed shadow 使用的安全 JSON fixture")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_dialogues is not None and args.max_dialogues < 1:
        print("错误: --max-dialogues 必须大于 0", file=sys.stderr)
        return 2
    if args.llm_mode == "replay" and not args.llm_replay_file:
        print("错误: replay 模式必须提供 --llm-replay-file", file=sys.stderr)
        return 2
    force_offline_environment()
    llm_module._env_file_values.cache_clear()
    try:
        samples = load_dataset(args.dataset)
    except DatasetValidationError as exc:
        print(f"数据集 schema 错误: {exc}", file=sys.stderr)
        return 2
    selected = filter_samples(
        samples,
        category=args.category,
        expected_result_type=args.expected_result_type,
        max_dialogues=args.max_dialogues,
    )
    if not selected:
        print("没有符合筛选条件的样本", file=sys.stderr)
        return 2
    service_factory = lambda: create_text_entry_service(args.llm_mode, args.llm_replay_file)
    results = asyncio.run(evaluate_samples(selected, verbose=args.verbose, service_factory=service_factory))
    summary = build_summary(results)
    print_report(results, summary)
    if args.json_report:
        write_json_report(args.json_report, results, summary)
    return 1 if args.fail_on_regression and summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
