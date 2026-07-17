# Synthetic safety and handoff API

All endpoints validate the restaurant/branch/session context. A case queried through another tenant returns the same `HANDOFF_NOT_FOUND` result as a nonexistent case. Request models reject extra fields, so callers cannot send a phone, address, card number, transcript, or real employee identity.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/safety/evaluate` | Persist a structured policy decision from signals/confidence metadata |
| `POST` | `/api/handoffs` | Idempotently request a synthetic case for a stable reason |
| `GET` | `/api/handoffs/{public_id}` | Read a tenant-scoped synthetic case |
| `POST` | `/api/handoffs/{public_id}/simulate-assign` | Move pending to simulated assigned |
| `POST` | `/api/handoffs/{public_id}/simulate-connect` | Move assigned to simulated connected |
| `POST` | `/api/handoffs/{public_id}/simulate-resolve` | Record a structured simulated resolution |
| `POST` | `/api/handoffs/{public_id}/simulate-fail` | Record a stable failure code |
| `POST` | `/api/handoffs/{public_id}/cancel` | Cancel only the handoff case |

Every Phase 3 safety/handoff endpoint requires `APP_ENV=development|test`, `SIMULATION_DATA_ONLY=true`, and `SIMULATION_HANDOFF_CONTROLS_ENABLED=true`. Production defaults to disabled and returns `SIMULATION_CONTROLS_DISABLED` without exposing the route's internal state. Read and control operations require the owning `sessionId` in addition to tenant codes; the same-tenant wrong-session case is reported as `HANDOFF_NOT_FOUND`.

`POST /api/safety/evaluate` accepts `sessionId`, optional tenant codes, a bounded stable-code signal list, requested action, required confirmation field names, optional strictly typed layered confidence metadata, and a `deterministicInput` flag. Nested extra fields are rejected, so confidence metadata cannot be used to smuggle a phone, address, card number, or transcript. It does not accept raw audio or require original user text.

`simulate-resolve` accepts only an uppercase `resolutionCode` and `draftChanged`. No API can set `MERCHANT_ACCEPTED`, connect a real person, take payment, issue a refund, place a phone call, or send a message.

Errors have the shape:

```json
{"error":{"code":"HANDOFF_NOT_FOUND","message":"The simulated handoff case was not found."}}
```
