# Simulated handoff failure policy

Stable failure codes are `NO_AGENT_AVAILABLE`, `QUEUE_TIMEOUT`, `ASSIGNMENT_FAILED`, `CONNECTION_FAILED`, `CASE_CANCELLED`, and `SYSTEM_ERROR`.

For every failure:

- the case becomes `FAILED` and writes an append-only event;
- the order remains a local synthetic draft or safety-held local confirmation;
- no merchant submission, payment, refund, SMS, callback, or phone call occurs;
- the response never says a human connected;
- the customer may cancel the simulated queue without cancelling the order draft;
- cancellation of `EXPLICIT_HUMAN_REQUEST` may resume only as `DRAFT`, after authoritative menu/price/availability checks and a new explicit confirmation;
- cancellation of every other reason retains the safety hold and cannot enable confirmation or submission;
- a later request may create a new simulated case;
- audit logs use structured IDs and codes only.

Callbacks are off and no callback field is accepted by the API. There is no automatic SMS fallback. Queue timeout and unavailable-agent simulations are states for testing product behavior, not measurements of a real queue or staffing promise.

`NO_AGENT_AVAILABLE`, `QUEUE_TIMEOUT`, `CONNECTION_FAILED`, and `SYSTEM_ERROR` never release an order hold or restore an old confirmation. The draft and its items remain local, no fallback order is created, and no failure path can produce merchant acceptance.

Summary generation failure follows the same fail-closed policy. Database/tenant errors return stable domain codes and omit SQL, stack traces, database URLs, and existence information from another tenant.
