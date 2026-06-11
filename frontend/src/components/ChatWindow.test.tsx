import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { ChatWindow } from "./ChatWindow";

const SESSION_STORAGE_KEY = "order_agent_session_id";

const voiceDisabledStatus = {
  voiceEnabled: false,
  canRecord: false,
  canSpeak: false,
  hints: [],
};

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("ChatWindow session persistence", () => {
  test("creates and stores a session id when localStorage is empty", () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("11111111-1111-4111-8111-111111111111");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okJson(voiceDisabledStatus)));

    render(<ChatWindow />);

    expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBe("11111111-1111-4111-8111-111111111111");
  });

  test("reuses a stored session id for chat requests after a refresh", async () => {
    localStorage.setItem(SESSION_STORAGE_KEY, "stored-session");
    const generated: ReturnType<typeof crypto.randomUUID>[] = [
      "22222222-2222-4222-8222-222222222222",
      "33333333-3333-4333-8333-333333333333",
    ];
    vi.spyOn(crypto, "randomUUID").mockImplementation(() => generated.shift() ?? "44444444-4444-4444-8444-444444444444");
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(voiceDisabledStatus));
      }
      if (url.includes("/chat")) {
        return Promise.resolve(okJson({ session_id: "stored-session", response: "好的", state: {}, trace: {} }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ChatWindow />);
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "有啥" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/chat"))).toBe(true));
    const chatCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/chat"));
    expect(JSON.parse(String((chatCall?.[1] as RequestInit).body))).toMatchObject({
      session_id: "stored-session",
      message: "有啥",
    });
  });

  test("reset starts a new stored session and clears current messages", async () => {
    localStorage.setItem(SESSION_STORAGE_KEY, "old-session");
    const generated: ReturnType<typeof crypto.randomUUID>[] = [
      "33333333-3333-4333-8333-333333333333",
      "44444444-4444-4444-8444-444444444444",
      "55555555-5555-4555-8555-555555555555",
      "66666666-6666-4666-8666-666666666666",
      "77777777-7777-4777-8777-777777777777",
    ];
    vi.spyOn(crypto, "randomUUID").mockImplementation(() => generated.shift() ?? "88888888-8888-4888-8888-888888888888");
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(voiceDisabledStatus));
      }
      if (url.includes("/chat")) {
        return Promise.resolve(okJson({ session_id: "old-session", response: "好的", state: {}, trace: {} }));
      }
      if (url.includes("/reset")) {
        return Promise.resolve(okJson({ ok: true }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ChatWindow />);
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "有啥" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);
    await screen.findByText("好的");

    fireEvent.click(screen.getByRole("button", { name: /重置|新订单/ }));

    await waitFor(() => expect(localStorage.getItem(SESSION_STORAGE_KEY)).toBe("55555555-5555-4555-8555-555555555555"));
    expect(screen.queryByText("有啥")).not.toBeInTheDocument();
    expect(screen.queryByText("好的")).not.toBeInTheDocument();

    fireEvent.change(textbox, { target: { value: "重新点" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/chat"))).toHaveLength(2));
    const chatCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/chat"));
    expect(JSON.parse(String((chatCalls[1][1] as RequestInit).body))).toMatchObject({
      session_id: "55555555-5555-4555-8555-555555555555",
      message: "重新点",
    });
  });
});

function okJson(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  };
}
