from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import ChatRequest, ResetRequest
from app.runtime import store, text_entry_service


router = APIRouter()


@router.post("/chat")
async def chat(request: ChatRequest) -> dict:
    result = await text_entry_service.handle_text_message(
        request.session_id,
        request.message,
        restaurant_code=request.restaurant_id,
        branch_code=request.branch_id,
        idempotency_key=request.idempotency_key,
    )
    return {
        "session_id": request.session_id,
        "response": result["response"],
        "state": result["state"],
        "trace": result["trace"],
        "lifecycleStatus": result["lifecycle_status"],
        "merchantStatus": result["merchant_status"],
        "submitted": result["submitted_deprecated"],
        "submittedDeprecated": True,
    }


@router.post("/reset")
def reset(request: ResetRequest) -> dict:
    state = store.reset(request.session_id, request.restaurant_id, request.branch_id)
    return {"session_id": request.session_id, "state": state.serializable()}
