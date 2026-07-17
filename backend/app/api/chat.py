from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import ChatRequest, ResetRequest
from app.runtime import database, store, text_entry_service


router = APIRouter()


@router.post("/chat")
async def chat(request: ChatRequest) -> dict:
    result = await text_entry_service.handle_text_message(
        request.session_id,
        request.message,
        restaurant_code=request.restaurant_id,
        branch_code=request.branch_id,
        idempotency_key=request.idempotency_key,
        confidence_metadata=request.confidence_metadata,
        locale=request.locale,
        locale_hint=request.locale_hint,
        locale_locked=request.locale_locked,
    )
    return {
        "session_id": request.session_id,
        "response": result["response"],
        "state": result["state"],
        "trace": _safe_trace(result["trace"], production=database.settings.app_env == "production"),
        "lifecycleStatus": result["lifecycle_status"],
        "merchantStatus": result["merchant_status"],
        "submitted": result["submitted_deprecated"],
        "submittedDeprecated": True,
        "detectedLocale": result.get("detected_locale", result["raw_state"].detected_locale),
        "dominantLocale": result.get("dominant_locale", result["raw_state"].dominant_locale),
        "responseLocale": result.get("response_locale", result["raw_state"].response_locale),
        "localeConfidence": result.get("locale_confidence", 1.0),
        "mixedLanguage": result.get("mixed_language", result["raw_state"].mixed_language),
        "requiredConfirmations": result.get("required_confirmations", result["raw_state"].unconfirmed_fields),
        "safetyClassification": result["raw_state"].safety_classification,
        "handoffStatus": result["raw_state"].handoff_status,
    }


@router.post("/reset")
def reset(request: ResetRequest) -> dict:
    state = store.reset(request.session_id, request.restaurant_id, request.branch_id)
    return {"session_id": request.session_id, "state": state.serializable()}


def _safe_trace(trace: dict, *, production: bool) -> dict:
    if production:
        allowed = {
            "finalIntent",
            "selectedAgent",
            "selectedHandler",
            "fallbackUsed",
            "stateMutationAllowed",
            "stateMutationRejectedReason",
            "lifecycleStatus",
            "merchantStatus",
            "draftVersion",
            "safety",
        }
        return {key: value for key, value in trace.items() if key in allowed}
    safe = dict(trace)
    safe.pop("userMessage", None)
    safe.pop("normalizedMessage", None)
    for key in (
        "officialAddressBefore",
        "officialAddressAfter",
        "pendingCandidateBefore",
        "pendingCandidateAfter",
    ):
        if safe.get(key):
            safe[key] = "[redacted]"
    return safe
