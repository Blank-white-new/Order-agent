# Simulated handoff failure policy

Stable failure codes are `NO_AGENT_AVAILABLE`, `QUEUE_TIMEOUT`, `ASSIGNMENT_FAILED`, `CONNECTION_FAILED`, `CASE_CANCELLED`, and `SYSTEM_ERROR`.

For every failure:

- the case becomes `FAILED` and writes an append-only event;
- the order remains a local synthetic draft or safety-held local confirmation;
- no merchant submission, payment, refund, SMS, callback, or phone call occurs;
- the response never says a human connected;
- the customer may cancel the handoff without cancelling the order;
- a later request may create a new simulated case;
- audit logs use structured IDs and codes only.

Callbacks are off and no callback field is accepted by the API. There is no automatic SMS fallback. Queue timeout and unavailable-agent simulations are states for testing product behavior, not measurements of a real queue or staffing promise.

Summary generation failure follows the same fail-closed policy. Database/tenant errors return stable domain codes and omit SQL, stack traces, database URLs, and existence information from another tenant.
