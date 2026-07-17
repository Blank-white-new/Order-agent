import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { normalizeOrderState } from "../types/order";
import { ChatWindow } from "./ChatWindow";
import { MessageBubble } from "./MessageBubble";
import { SafetyHandoffPanel } from "./SafetyHandoffPanel";


beforeEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});


describe("Phase 4 multilingual text controls", () => {
  test("offers auto detection and three concrete reply languages accessibly", () => {
    vi.stubGlobal("fetch", multilingualFetch());
    render(<ChatWindow />);
    const selector = screen.getByRole("combobox", { name: "回复语言" });
    expect(selector).toHaveValue("auto");
    expect(screen.getByRole("option", { name: "普通话" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "廣東話" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "English" })).toBeInTheDocument();
    expect(screen.getByText(/多语言能力仅限文字/)).toBeInTheDocument();
  });

  test("English selection localizes the interface and sends locked locale metadata", async () => {
    const fetchMock = multilingualFetch();
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatWindow />);
    fireEvent.change(screen.getByRole("combobox", { name: "回复语言" }), { target: { value: "en-HK" } });
    expect(screen.getByRole("heading", { name: "Ordering assistant" })).toBeInTheDocument();
    expect(screen.getByText(/The language option is updated/)).toBeInTheDocument();
    expect(screen.queryByText("语音输入")).not.toBeInTheDocument();
    const input = screen.getByRole("textbox", { name: "Enter an ordering message" });
    fireEvent.change(input, { target: { value: "I want two portions chicken leg rice" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    expect(await screen.findByText("Please clarify the quantity.")).toBeInTheDocument();
    expect(screen.getByText("Mixed-language input")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Clarification required" })).toBeInTheDocument();
    const chatCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/chat"));
    expect(JSON.parse(String((chatCall?.[1] as RequestInit).body))).toMatchObject({
      locale: "en-HK",
      localeHint: "en-HK",
      localeLocked: true,
    });
  });

  test("changing language does not clear the authoritative order summary", async () => {
    vi.stubGlobal("fetch", multilingualFetch({
      requiredConfirmations: [],
      mixedLanguage: false,
      detectedLocale: "zh-CN",
      responseLocale: "zh-CN",
      response: "已加入鸡腿饭。",
      state: {
        current_order: [{ item_id: "chicken_leg_rice", name: "鸡腿饭", quantity: 1, price: 26, category: "饭类" }],
      },
    }));
    render(<ChatWindow />);
    const input = screen.getByRole("textbox", { name: "输入点餐消息" });
    fireEvent.change(input, { target: { value: "我要一份鸡腿饭" } });
    fireEvent.submit(input.closest("form") as HTMLFormElement);
    expect(await screen.findByText("鸡腿饭")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "回复语言" }), { target: { value: "yue-Hant-HK" } });
    expect(screen.getByText("鸡腿饭")).toBeInTheDocument();
    expect(screen.getByText(/目前張單唔會被清空/)).toBeInTheDocument();
  });
});


describe("localized safety and production-safe presentation", () => {
  test.each([
    ["yue-Hant-HK", "模擬接管，唔係真人"],
    ["en-HK", "Simulated handoff — not a real person"],
  ] as const)("renders explicit non-human handoff warning in %s", (locale, warning) => {
    render(
      <SafetyHandoffPanel
        sessionId="synthetic-session"
        locale={locale}
        state={normalizeOrderState({
          safety_classification: "HANDOFF",
          safety_reason_code: "SEVERE_ALLERGY",
          handoff_public_id: "SIM-HO-TEST",
          handoff_status: "PENDING",
        })}
      />,
    );
    expect(screen.getByText(warning)).toBeInTheDocument();
  });

  test("safety status is rendered as text and not conveyed by colour alone", () => {
    render(
      <SafetyHandoffPanel
        sessionId="synthetic-session"
        locale="en-HK"
        state={normalizeOrderState({ safety_classification: "REFUSE" })}
      />,
    );
    expect(screen.getByText("Refused")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("No successful result");
  });

  test("parser debug remains collapsed and contains no raw input field", () => {
    render(
      <MessageBubble
        role="agent"
        text="Safe response"
        trace={{ multilingual: { canonicalIntent: "ADD_ITEM" } }}
        debugLabel="Debug information"
      />,
    );
    const details = screen.getByText("Debug information").closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(details).not.toHaveTextContent("userMessage");
  });
});


function multilingualFetch(overrides: Record<string, unknown> = {}) {
  return vi.fn((url: string, _init?: RequestInit) => {
    if (url.includes("/voice/status")) {
      return Promise.resolve(okJson({ voiceEnabled: false, canRecord: false, canSpeak: false, hints: [] }));
    }
    if (url.includes("/menu")) {
      return Promise.resolve(okJson({ categories: [], items: [] }));
    }
    if (url.includes("/chat")) {
      return Promise.resolve(okJson({
        session_id: "synthetic-session",
        response: "Please clarify the quantity.",
        state: {
          current_order: [{
            item_id: "chicken_leg_rice",
            name: "雞髀飯",
            quantity: 1,
            price: 26,
            category: "飯類",
          }],
        },
        trace: {},
        detectedLocale: "mixed",
        dominantLocale: "en-HK",
        responseLocale: "en-HK",
        localeConfidence: 0.94,
        mixedLanguage: true,
        requiredConfirmations: ["quantity"],
        safetyClassification: "CONFIRM",
        handoffStatus: "NOT_REQUIRED",
        ...overrides,
      }));
    }
    return Promise.resolve(okJson({ state: {} }));
  });
}


function okJson(body: unknown): Response {
  return { ok: true, json: async () => body } as Response;
}
