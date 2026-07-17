import { MenuView, normalizeMenuResponse, normalizeOrderState, OrderStateView } from "../types/order";
import { ConcreteLocale } from "../i18n";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export type ChatResponse = {
  session_id: string;
  response: string;
  state: OrderStateView;
  trace: Record<string, unknown>;
  detectedLocale: string;
  dominantLocale: ConcreteLocale;
  responseLocale: ConcreteLocale;
  localeConfidence: number;
  mixedLanguage: boolean;
  requiredConfirmations: string[];
  safetyClassification: string;
  handoffStatus: string;
};

export type ChatLocaleOptions = {
  locale?: ConcreteLocale;
  localeHint?: ConcreteLocale;
  localeLocked?: boolean;
};

export async function sendChatMessage(
  sessionId: string,
  message: string,
  localeOptions: ChatLocaleOptions = {},
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message, ...localeOptions }),
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
    detectedLocale: optionalLocale(body.detectedLocale) ?? "zh-CN",
    dominantLocale: concreteLocale(body.dominantLocale),
    responseLocale: concreteLocale(body.responseLocale),
    localeConfidence: finiteNumber(body.localeConfidence) ?? 0,
    mixedLanguage: body.mixedLanguage === true,
    requiredConfirmations: stringList(body.requiredConfirmations),
    safetyClassification: typeof body.safetyClassification === "string" ? body.safetyClassification : "AUTO_DRAFT",
    handoffStatus: typeof body.handoffStatus === "string" ? body.handoffStatus : "NOT_REQUIRED",
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

export async function getMenu(locale: ConcreteLocale = "zh-CN"): Promise<MenuView> {
  const response = await fetch(`${API_BASE}/menu?locale=${encodeURIComponent(locale)}`);
  if (!response.ok) {
    throw new Error("menu request failed");
  }
  return normalizeMenuResponse(await response.json());
}

function optionalLocale(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function concreteLocale(value: unknown): ConcreteLocale {
  return value === "yue-Hant-HK" || value === "en-HK" ? value : "zh-CN";
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

