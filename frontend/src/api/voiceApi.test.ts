import { afterEach, describe, expect, test, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("getVoiceWebSocketUrl", () => {
  test("uses the default local API base when VITE_API_BASE_URL is unset", async () => {
    const { getVoiceWebSocketUrl } = await loadVoiceApi(undefined);

    expect(getVoiceWebSocketUrl("session 1")).toBe("ws://localhost:8000/api/voice/asr?session_id=session%201");
  });

  test("converts absolute http API base to ws", async () => {
    const { getVoiceWebSocketUrl } = await loadVoiceApi("http://localhost:8000/api");

    expect(getVoiceWebSocketUrl("s1")).toBe("ws://localhost:8000/api/voice/asr?session_id=s1");
  });

  test("converts absolute https API base to wss", async () => {
    const { getVoiceWebSocketUrl } = await loadVoiceApi("https://example.com/api");

    expect(getVoiceWebSocketUrl("s1")).toBe("wss://example.com/api/voice/asr?session_id=s1");
  });

  test("resolves a relative API base against the current page origin", async () => {
    const { getVoiceWebSocketUrl } = await loadVoiceApi("/api");
    const expectedProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";

    expect(getVoiceWebSocketUrl("s1")).toBe(`${expectedProtocol}//${window.location.host}/api/voice/asr?session_id=s1`);
  });
});

async function loadVoiceApi(apiBase: string | undefined) {
  vi.resetModules();
  vi.stubEnv("VITE_API_BASE_URL", apiBase);
  return import("./voiceApi");
}
