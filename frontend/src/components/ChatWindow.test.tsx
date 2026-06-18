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
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("ChatWindow session persistence", () => {
  test("creates and stores a session id when localStorage is empty", () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("11111111-1111-4111-8111-111111111111");
    vi.stubGlobal("fetch", makeFetchMock());

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
    const fetchMock = makeFetchMock({ chatResponse: { session_id: "stored-session", response: "好的", state: {}, trace: {} } });
    vi.stubGlobal("fetch", fetchMock);

    render(<ChatWindow />);
    const textbox = screen.getByRole("textbox", { name: "输入点餐消息" });
    fireEvent.change(textbox, { target: { value: "有啥" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    await screen.findByText("好的");
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
    const fetchMock = makeFetchMock({ chatResponse: { session_id: "old-session", response: "好的", state: {}, trace: {} } });
    vi.stubGlobal("fetch", fetchMock);

    render(<ChatWindow />);
    const textbox = screen.getByRole("textbox", { name: "输入点餐消息" });
    fireEvent.change(textbox, { target: { value: "有啥" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);
    await screen.findByText("好的");

    fireEvent.click(screen.getByRole("button", { name: "新订单" }));

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

describe("ChatWindow order UX", () => {
  test("updates the text-chat order summary from chat state", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        chatResponse: {
          session_id: "s1",
          response: "已加入黑椒牛肉饭。",
          state: {
            current_order: [{ item_id: "black_pepper_beef_rice", name: "黑椒牛肉饭", price: 30, quantity: 2, category: "饭类" }],
            fulfillment_type: "delivery",
          },
          trace: {},
        },
      }),
    );

    render(<ChatWindow />);
    const textbox = screen.getByRole("textbox", { name: "输入点餐消息" });
    fireEvent.change(textbox, { target: { value: "黑椒牛肉饭吧" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    expect(await screen.findByText("已加入黑椒牛肉饭。")).toBeInTheDocument();
    expect(screen.getByText("当前文本对话订单状态")).toBeInTheDocument();
    expect(screen.getByText("基于文字聊天最近返回的状态显示")).toBeInTheDocument();
    expect(screen.getByText("黑椒牛肉饭")).toBeInTheDocument();
    expect(screen.getByText("饭类 · 2份")).toBeInTheDocument();
    expect(screen.getByText("小计：60 元")).toBeInTheDocument();
  });

  test("renders user and agent messages with long recommendation-style replies", async () => {
    vi.stubGlobal(
      "fetch",
      makeFetchMock({
        chatResponse: {
          session_id: "s1",
          response: "推荐：\n1. 鸡腿饭，26 元，适合不辣。\n2. 黑椒牛肉饭，30 元，香味更重。",
          state: {},
          trace: {},
        },
      }),
    );

    render(<ChatWindow />);
    const textbox = screen.getByRole("textbox", { name: "输入点餐消息" });
    fireEvent.change(textbox, { target: { value: "招牌菜是啥" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    expect(await screen.findByText("招牌菜是啥")).toBeInTheDocument();
    expect(await screen.findByText((content) => content.includes("黑椒牛肉饭，30 元"))).toBeInTheDocument();
  });

  test("shows sending state and a recoverable network error", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const chatDeferred = createDeferred<ReturnType<typeof okJson>>();
    vi.stubGlobal("fetch", makeFetchMock({ chatPromise: chatDeferred.promise }));

    render(<ChatWindow />);
    const textbox = screen.getByRole("textbox", { name: "输入点餐消息" });
    fireEvent.change(textbox, { target: { value: "来一份米饭" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    expect(await screen.findByText("正在发送...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送中" })).toBeDisabled();

    chatDeferred.reject(new Error("offline"));

    expect(await screen.findByRole("alert")).toHaveTextContent("后端暂时没连上");
    expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
  });

  test("menu clicks fill the input without submitting a chat request", async () => {
    const fetchMock = makeFetchMock({
      menuResponse: {
        categories: ["饭类"],
        items: [{ id: "chicken_leg_rice", name: "鸡腿饭", category: "饭类", price: 26 }],
      },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ChatWindow />);
    fireEvent.click(await screen.findByRole("button", { name: "填入我要一份鸡腿饭" }));

    expect(screen.getByRole("textbox", { name: "输入点餐消息" })).toHaveValue("我要一份鸡腿饭");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/chat"))).toBe(false);
  });
});

function makeFetchMock(options: { chatResponse?: unknown; chatPromise?: Promise<ReturnType<typeof okJson>>; menuResponse?: unknown } = {}) {
  return vi.fn((url: string, _init?: RequestInit) => {
    if (url.includes("/voice/status")) {
      return Promise.resolve(okJson(voiceDisabledStatus));
    }
    if (url.includes("/menu")) {
      return Promise.resolve(okJson(options.menuResponse ?? { items: [], categories: [] }));
    }
    if (url.includes("/chat")) {
      return options.chatPromise ?? Promise.resolve(okJson(options.chatResponse ?? { session_id: "s1", response: "好的", state: {}, trace: {} }));
    }
    if (url.includes("/reset")) {
      return Promise.resolve(okJson({ ok: true, state: {} }));
    }
    return Promise.resolve(okJson({}));
  });
}

function okJson(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
