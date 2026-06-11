export const ORDER_SESSION_STORAGE_KEY = "order_agent_session_id";

export function getOrCreateSessionId(): string {
  const existing = readStoredSessionId();
  if (existing) {
    return existing;
  }
  return createAndStoreSessionId();
}

export function createAndStoreSessionId(): string {
  const sessionId = crypto.randomUUID();
  try {
    localStorage.removeItem(ORDER_SESSION_STORAGE_KEY);
    localStorage.setItem(ORDER_SESSION_STORAGE_KEY, sessionId);
  } catch (err) {
    console.warn("Failed to persist order session id.", err);
  }
  return sessionId;
}

function readStoredSessionId(): string | null {
  try {
    const stored = localStorage.getItem(ORDER_SESSION_STORAGE_KEY);
    return stored?.trim() ? stored : null;
  } catch (err) {
    console.warn("Failed to read order session id.", err);
    return null;
  }
}
