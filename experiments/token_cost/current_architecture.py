from __future__ import annotations

from typing import Any


def summarize_runtime_result(result: dict[str, Any]) -> dict[str, Any]:
    trace = result.get("trace") or {}
    safety = trace.get("safety") or {}
    interpretation = trace.get("interpretation") or {}
    # Live fallback remains disabled for the experiment. A deterministic fallback
    # path is not an LLM request and therefore contributes zero prompt tokens.
    llm_required = bool(trace.get("liveLlmUsed") or trace.get("llmProviderInvoked"))
    return {
        "current_llm_required": llm_required,
        "current_input_tokens": 0,
        "current_output_token_budget": 0,
        "current_total_projected_tokens": 0,
        "current_context_tokens": 0,
        "current_llm_calls": int(llm_required),
        "canonical_intent": trace.get("finalIntent") or interpretation.get("intent") or "",
        "selected_handler": trace.get("selectedHandler") or "",
        "decision_class": safety.get("classification") or result.get("state", {}).get("safety_classification") or "",
        "fallback_used": bool(trace.get("fallbackUsed", False)),
        "execution_path": trace.get("executionPath") or "",
        "response": str(result.get("response") or ""),
    }
