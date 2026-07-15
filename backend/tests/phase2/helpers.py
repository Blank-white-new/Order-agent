from __future__ import annotations

from app.state.session_state import OrderItem, SessionState


def persisted_state(context, session_key: str, *, restaurant: str = "hk-sim-restaurant-a", branch: str = "central") -> SessionState:
    state = context.session_store.get(session_key, restaurant, branch)
    state.current_order = [
        OrderItem(
            item_id="chicken_leg_rice",
            name="stale client name",
            price=1,
            unit_price_minor=1,
            currency="HKD",
            quantity=1,
        )
    ]
    state.fulfillment_type = "pickup"
    state.stage = "confirming"
    context.session_store.set(session_key, state, restaurant, branch)
    return state
