const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export type HandoffView = {
  handoffId: string;
  status: string;
  reasonCode: string;
  failureCode: string | null;
  simulationNotice: string;
};

async function action(publicId: string, operation: string, payload: Record<string, unknown> = {}): Promise<HandoffView> {
  const response = await fetch(`${API_BASE}/handoffs/${encodeURIComponent(publicId)}/${operation}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("simulated handoff request failed");
  }
  const body = (await response.json()) as Record<string, unknown>;
  return {
    handoffId: stringValue(body.handoffId) ?? publicId,
    status: stringValue(body.status) ?? "FAILED",
    reasonCode: stringValue(body.reasonCode) ?? "SYSTEM_FAILURE",
    failureCode: stringValue(body.failureCode),
    simulationNotice: stringValue(body.simulationNotice) ?? "模拟人工接管，不是真实人工",
  };
}

export function simulateAssign(publicId: string): Promise<HandoffView> {
  return action(publicId, "simulate-assign");
}

export function simulateConnect(publicId: string): Promise<HandoffView> {
  return action(publicId, "simulate-connect");
}

export function simulateResolve(publicId: string): Promise<HandoffView> {
  return action(publicId, "simulate-resolve", { resolutionCode: "SIMULATED_REVIEWED", draftChanged: false });
}

export function simulateFail(publicId: string): Promise<HandoffView> {
  return action(publicId, "simulate-fail", { failureCode: "SYSTEM_ERROR" });
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}
