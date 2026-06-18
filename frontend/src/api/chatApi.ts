import { MenuView, normalizeMenuResponse, normalizeOrderState, OrderStateView } from "../types/order";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export type ChatResponse = {
  session_id: string;
  response: string;
  state: OrderStateView;
  trace: Record<string, unknown>;
};

export async function sendChatMessage(sessionId: string, message: string): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!response.ok) {
    throw new Error("chat request failed");
  }
  const body = (await response.json()) as Record<string, unknown>;
  return {
    session_id: typeof body.session_id === "string" ? body.session_id : sessionId,
    response: typeof body.response === "string" ? body.response : "",
    state: normalizeOrderState(body.state),
    trace: isRecord(body.trace) ? body.trace : {},
  };
}

export async function resetSession(sessionId: string): Promise<{ session_id: string; state: OrderStateView }> {
  const response = await fetch(`${API_BASE}/reset`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) {
    throw new Error("reset request failed");
  }
  const body = (await response.json()) as Record<string, unknown>;
  return {
    session_id: typeof body.session_id === "string" ? body.session_id : sessionId,
    state: normalizeOrderState(body.state),
  };
}

export async function getMenu(): Promise<MenuView> {
  const response = await fetch(`${API_BASE}/menu`);
  if (!response.ok) {
    throw new Error("menu request failed");
  }
  return normalizeMenuResponse(await response.json());
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

