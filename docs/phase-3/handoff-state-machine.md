# Simulated handoff state machine

The only provider is `SimulationHandoffProvider`. No state means a real person is available or connected.

| Current | Allowed next states |
|---|---|
| `NOT_REQUIRED` | `REQUESTED` |
| `REQUESTED` | `PENDING`, `FAILED`, `CANCELLED` |
| `PENDING` | `SIMULATED_AGENT_ASSIGNED`, `FAILED`, `CANCELLED` |
| `SIMULATED_AGENT_ASSIGNED` | `SIMULATED_AGENT_CONNECTED`, `FAILED`, `CANCELLED` |
| `SIMULATED_AGENT_CONNECTED` | `RESOLVED`, `FAILED`, `CANCELLED` |
| `RESOLVED` | none |
| `FAILED` | none; a later request creates a new case |
| `CANCELLED` | none; a later request creates a new case |

`HUMAN_CONNECTED` is deliberately absent. UI and API labels always say `SIMULATED_AGENT_CONNECTED` and “模拟人工接管，不是真实人工”. Every transition is validated by `HandoffService` and appends a sequenced `HandoffEvent`.

## Ordering interaction

- Creating a handoff invalidates the current confirmation, moves the in-session draft back to `DRAFT`, and places `safety_hold=true` on an existing local confirmed order.
- `OrderLifecycleService` rejects submission, merchant-pending, and merchant-accepted transitions while the hold is present.
- Failure and cancellation do not submit or cancel the order draft.
- A mandatory reason such as severe allergy cannot be bypassed by “continue myself”; cancelling that case causes the safety guard to recreate it on the next protected goal.
- A simulated resolution does not clear merchant status and never creates merchant acceptance.
- If a simulation resolution declares `draftChanged=true`, the persisted draft version increments, the old confirmation remains invalid, and the local order returns to `DRAFT`. A new explicit customer confirmation is required.

## Idempotency and concurrency

A partial unique index permits only one active case per session. Repeating the same request reuses the case. A different active risk reason appends `HANDOFF_RISK_UPDATED`, unions risk/blocked-action fields, and can raise priority. Repository locking plus the unique constraint makes concurrent creation converge on one active case on SQLite and PostgreSQL.
