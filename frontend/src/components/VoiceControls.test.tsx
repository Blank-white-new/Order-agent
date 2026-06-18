import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { ChatWindow } from "./ChatWindow";
import { VoiceStatus, VoiceTtsStatus } from "../api/voiceApi";
import { VoiceControls } from "./VoiceControls";

const baseStatus: VoiceStatus = {
  voiceEnabled: false,
  asrEngine: "vosk",
  ttsEnabled: true,
  ttsEngine: "pyttsx3",
  ttsPlaybackTarget: "server",
  asrReady: false,
  ttsReady: false,
  asrDependencyAvailable: false,
  ttsDependencyAvailable: false,
  modelPathExists: false,
  modelLooksValid: false,
  modelLoaded: false,
  canRecord: false,
  canSpeak: false,
  asrDisabledReason: "ASR 模型路径不存在",
  ttsDisabledReason: "TTS 依赖缺失",
  disabledReason: "后端语音未开启",
  hints: ["请在后端 .env 中设置 VOICE_ENABLED=true"],
  envFilePath: "D:/project/.env",
  envFileExists: false,
  voskModelPath: "./models/asr/vosk-cn",
};

const readyStatus: VoiceStatus = {
  ...baseStatus,
  voiceEnabled: true,
  asrReady: true,
  ttsReady: true,
  asrDependencyAvailable: true,
  ttsDependencyAvailable: true,
  modelPathExists: true,
  modelLooksValid: true,
  canRecord: true,
  canSpeak: true,
  disabledReason: null,
  asrDisabledReason: null,
  ttsDisabledReason: null,
};

const idleTtsStatus: VoiceTtsStatus = {
  queueInitialized: true,
  speaking: false,
  queueSize: 0,
  maxQueueSize: 10,
  lastQueuedAt: null,
  lastStartedAt: null,
  lastFinishedAt: null,
  lastSuccess: null,
  lastError: null,
  lastTextLength: 0,
  lastTextPreview: null,
  currentVoice: { id: "fake", name: "Fake Voice", languages: ["zh"] },
  playbackTarget: "server",
  currentDurationMs: 0,
  maybeStuck: false,
  lastSource: null,
};

const speakingTtsStatus: VoiceTtsStatus = {
  ...idleTtsStatus,
  speaking: true,
  queueSize: 1,
  lastQueuedAt: "2026-05-25T00:00:00Z",
  lastStartedAt: "2026-05-25T00:00:01Z",
  lastTextLength: 3,
  lastTextPreview: "旧播报",
  currentDurationMs: 1200,
};

const getUserMedia = vi.fn();
let socketInstances: MockWebSocket[] = [];
let lastTrackStop = vi.fn();
let lastAudioClose = vi.fn();
let lastDestination: object;
let lastSource: { connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn> };
let lastSilentGain: { connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn>; gain: { value: number } };
let lastProcessor: { connect: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn>; onaudioprocess: ((event: AudioProcessingEvent) => void) | null };

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static autoOpen = true;
  static failOpen = false;

  readyState = MockWebSocket.CONNECTING;
  sent: unknown[] = [];
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new Event("close"));
  });
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(public url: string) {
    socketInstances.push(this);
    if (MockWebSocket.autoOpen) {
      queueMicrotask(() => {
        if (MockWebSocket.failOpen) {
          this.onerror?.(new Event("error"));
          return;
        }
        this.readyState = MockWebSocket.OPEN;
        this.onopen?.(new Event("open"));
      });
    }
  }

  send(payload: unknown) {
    this.sent.push(payload);
  }

  emitJson(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent);
  }

  emitRaw(data: unknown) {
    this.onmessage?.({ data } as MessageEvent);
  }

  unexpectedClose() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new Event("close"));
  }
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  socketInstances = [];
  MockWebSocket.autoOpen = true;
  MockWebSocket.failOpen = false;
  getUserMedia.mockReset();
  lastTrackStop = vi.fn();
  lastAudioClose = vi.fn(() => Promise.resolve());
  lastDestination = {};
  lastSource = { connect: vi.fn(), disconnect: vi.fn() };
  lastSilentGain = { connect: vi.fn(), disconnect: vi.fn(), gain: { value: 1 } };
  lastProcessor = { connect: vi.fn(), disconnect: vi.fn(), onaudioprocess: null };
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia },
    configurable: true,
  });
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal("AudioContext", MockAudioContext);
  vi.stubGlobal("webkitAudioContext", undefined);
});

describe("VoiceControls status sync", () => {
  test("disables voice controls when backend voice is disabled", async () => {
    renderWithStatus({ ...baseStatus, voiceEnabled: false, canRecord: false });

    const start = await screen.findByRole("button", { name: "开始说话" });
    const stop = screen.getByRole("button", { name: "停止说话" });
    expect(start).toBeDisabled();
    expect(stop).toBeDisabled();
    expect(start).toHaveClass("voice-button-disabled");
    expect(screen.getByLabelText("语音输入")).toBeDisabled();
    expect(screen.getByText(/后端语音功能未开启/)).toBeInTheDocument();

    fireEvent.click(start);
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(socketInstances).toHaveLength(0);
  });

  test("shows loading state while status is pending", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(<VoiceControls sessionId="s1" onUserFinal={vi.fn()} onAgentReply={vi.fn()} />);

    expect(screen.getByText(/正在检查后端语音状态/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "开始说话" })).toBeDisabled();
    expect(screen.getByLabelText("语音输入")).toBeDisabled();
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(socketInstances).toHaveLength(0);
  });

  test("shows request failure without affecting text chat input", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/voice/status")) {
        return Promise.reject(new Error("offline"));
      }
      if (url.includes("/chat")) {
        return Promise.resolve(okJson({ session_id: "s1", response: "好的", state: {}, trace: {} }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatWindow />);

    await waitFor(() => expect(screen.getAllByText(/无法获取后端语音状态/).length).toBeGreaterThan(0));
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "有啥" } });
    expect(textbox).toHaveValue("有啥");
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/chat"), expect.anything()));
  });

  test("text chat agent reply is queued for TTS when voice broadcast is enabled", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(readyStatus));
      }
      if (url.includes("/chat")) {
        return Promise.resolve(okJson({ session_id: "s1", response: "好的，已加入一份米饭", state: {}, trace: {} }));
      }
      if (url.includes("/voice/tts")) {
        return Promise.resolve(okJson({ ok: true, queued: true, playbackTarget: "server" }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatWindow />);

    const ttsToggle = await screen.findByLabelText("语音播报");
    fireEvent.click(ttsToggle);
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "来一份米饭" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    await waitFor(() => expect(screen.getByText("好的，已加入一份米饭")).toBeInTheDocument());
    await waitFor(() => expect(voiceTtsQueueCalls(fetchMock)).toHaveLength(1));
    const ttsCall = voiceTtsQueueCalls(fetchMock)[0];
    expect(ttsCall?.[1]).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    expect(JSON.parse(String((ttsCall?.[1] as RequestInit).body))).toMatchObject({
      text: "好的，已加入一份米饭",
    });
  });

  test("text chat does not queue TTS when voice broadcast is off", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(readyStatus));
      }
      if (url.includes("/chat")) {
        return Promise.resolve(okJson({ session_id: "s1", response: "好的，已加入一份米饭", state: {}, trace: {} }));
      }
      if (url.includes("/voice/tts")) {
        return Promise.resolve(okJson({ ok: true, queued: true, playbackTarget: "server" }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatWindow />);

    await screen.findByLabelText("语音播报");
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "来一份米饭" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/chat"), expect.anything()));
    expect(voiceTtsQueueCalls(fetchMock)).toHaveLength(0);
  });

  test("text chat does not queue TTS when backend cannot speak", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson({ ...readyStatus, canSpeak: false }));
      }
      if (url.includes("/chat")) {
        return Promise.resolve(okJson({ session_id: "s1", response: "好的，已加入一份米饭", state: {}, trace: {} }));
      }
      if (url.includes("/voice/tts")) {
        return Promise.resolve(okJson({ ok: true, queued: true, playbackTarget: "server" }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatWindow />);

    expect(await screen.findByLabelText("语音播报")).toBeDisabled();
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "来一份米饭" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/chat"), expect.anything()));
    expect(voiceTtsQueueCalls(fetchMock)).toHaveLength(0);
  });

  test("text chat still displays reply when TTS queue request fails", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(readyStatus));
      }
      if (url.includes("/chat")) {
        return Promise.resolve(okJson({ session_id: "s1", response: "好的，已加入一份米饭", state: {}, trace: {} }));
      }
      if (url.includes("/voice/tts")) {
        return Promise.reject(new Error("tts offline"));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ChatWindow />);

    fireEvent.click(await screen.findByLabelText("语音播报"));
    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "来一份米饭" } });
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);

    await waitFor(() => expect(screen.getByText("好的，已加入一份米饭")).toBeInTheDocument());
    await waitFor(() => expect(warnSpy).toHaveBeenCalledWith("Text reply TTS request failed.", expect.any(Error)));
  });

  test("falls back for missing fields but rejects malformed field types", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(okJson({}))
      .mockResolvedValueOnce(okJson({ canRecord: "true", hints: [] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<VoiceControls sessionId="s1" onUserFinal={vi.fn()} onAgentReply={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "开始说话" })).toBeDisabled();
    expect(screen.queryByText(/语音状态响应格式异常/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "刷新语音状态" }));
    await waitFor(() => expect(screen.getAllByText(/语音状态响应格式异常/).length).toBeGreaterThan(0));
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(socketInstances).toHaveLength(0);
  });

  test("disables start when model path is missing", async () => {
    renderWithStatus({
      ...baseStatus,
      voiceEnabled: true,
      disabledReason: "ASR 模型路径不存在",
      asrDisabledReason: "ASR 模型路径不存在",
      modelPathExists: false,
      modelLooksValid: false,
      canRecord: false,
    });

    expect(await screen.findByRole("button", { name: "开始说话" })).toBeDisabled();
    expect(screen.getAllByText(/ASR 模型路径不存在/).length).toBeGreaterThan(0);
  });

  test("disables start when model directory structure is invalid", async () => {
    renderWithStatus({
      ...baseStatus,
      voiceEnabled: true,
      disabledReason: "ASR 模型目录结构无效",
      asrDisabledReason: "ASR 模型目录结构无效",
      asrDependencyAvailable: true,
      modelPathExists: true,
      modelLooksValid: false,
      canRecord: false,
    });

    expect(await screen.findByRole("button", { name: "开始说话" })).toBeDisabled();
    expect(screen.getAllByText(/ASR 模型目录结构无效/).length).toBeGreaterThan(0);
  });

  test("requires user preference before starting when canRecord is true", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus);

    const start = await screen.findByRole("button", { name: "开始说话" });
    expect(start).toBeDisabled();

    fireEvent.click(screen.getByLabelText("语音输入"));
    expect(start).toBeEnabled();
    fireEvent.click(start);

    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(socketInstances).toHaveLength(1));
    await waitFor(() => expect(socketInstances[0].sent).toHaveLength(1));
    expect(parseJsonMessage(socketInstances[0].sent[0]).tts_enabled).toBe(false);
  });

  test("speaking TTS status does not disable starting a voice round", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(readyStatus));
      }
      if (url.includes("/voice/tts/status")) {
        return Promise.resolve(okJson(speakingTtsStatus));
      }
      if (url.includes("/voice/tts")) {
        return Promise.resolve(okJson({ ok: true, queued: true, playbackTarget: "server" }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VoiceControls sessionId="s1" onUserFinal={vi.fn()} onAgentReply={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "测试播报" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/voice/tts/status")));
    fireEvent.click(screen.getByLabelText("语音输入"));

    expect(screen.getByRole("button", { name: "开始说话" })).toBeEnabled();
  });

  test("stops active TTS before starting recording", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(readyStatus));
      }
      if (url.includes("/voice/tts/status")) {
        return Promise.resolve(okJson(speakingTtsStatus));
      }
      if (url.includes("/voice/tts/stop")) {
        return Promise.resolve(okJson({ ok: true, stopped: true, interrupted: true, clearedJobs: 1, status: idleTtsStatus }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VoiceControls sessionId="s1" onUserFinal={vi.fn()} onAgentReply={vi.fn()} />);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/voice/tts/status")));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/voice/tts/stop"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));
    expect(screen.getByLabelText("语音输入")).toBeChecked();
    expect(screen.getByRole("button", { name: "停止说话" })).toBeEnabled();
    expect(socketInstances[0].close).not.toHaveBeenCalled();
  });

  test("waits for TTS stop before opening the microphone", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    const stopDeferred = createDeferred<ReturnType<typeof okJson>>();
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(readyStatus));
      }
      if (url.includes("/voice/tts/status")) {
        return Promise.resolve(okJson(speakingTtsStatus));
      }
      if (url.includes("/voice/tts/stop")) {
        return stopDeferred.promise;
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VoiceControls sessionId="s1" onUserFinal={vi.fn()} onAgentReply={vi.fn()} />);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/voice/tts/stop"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(getUserMedia).not.toHaveBeenCalled();

    stopDeferred.resolve(okJson({ ok: true, stopped: true, interrupted: true, clearedJobs: 1, status: idleTtsStatus }));

    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));
  });

  test("ScriptProcessor fallback routes through muted gain and clears output", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    expect(lastSource.connect).toHaveBeenCalledWith(lastProcessor);
    expect(lastProcessor.connect).not.toHaveBeenCalledWith(lastDestination);
    expect(lastProcessor.connect).toHaveBeenCalledWith(lastSilentGain);
    expect(lastSilentGain.gain.value).toBe(0);
    expect(lastSilentGain.connect).toHaveBeenCalledWith(lastDestination);

    const input = new Float32Array([0.25, -0.5]);
    const outputLeft = new Float32Array([1, 2, 3]);
    const outputRight = new Float32Array([4, 5, 6]);
    const outputBuffer = {
      numberOfChannels: 2,
      getChannelData: vi.fn((index: number) => (index === 0 ? outputLeft : outputRight)),
    };

    lastProcessor.onaudioprocess?.({
      inputBuffer: { getChannelData: vi.fn(() => input) },
      outputBuffer,
    } as unknown as AudioProcessingEvent);

    expect(Array.from(outputLeft)).toEqual([0, 0, 0]);
    expect(Array.from(outputRight)).toEqual([0, 0, 0]);
  });

  test("does not stop idle TTS before starting recording", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(readyStatus));
      }
      if (url.includes("/voice/tts/status")) {
        return Promise.resolve(okJson(idleTtsStatus));
      }
      if (url.includes("/voice/tts/stop")) {
        return Promise.resolve(okJson({ ok: true, stopped: false, interrupted: false, clearedJobs: 0, status: idleTtsStatus }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VoiceControls sessionId="s1" onUserFinal={vi.fn()} onAgentReply={vi.fn()} />);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));

    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/voice/tts/stop"))).toBe(false);
  });

  test("start_utterance carries current TTS preference for consecutive rounds", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus);

    await waitFor(() => expect(screen.getAllByRole("button").length).toBeGreaterThanOrEqual(4));
    const [voiceInput, ttsInput] = screen.getAllByRole("checkbox");
    const start = () => screen.getAllByRole("button")[2];
    const stop = () => screen.getAllByRole("button")[3];
    fireEvent.click(voiceInput);
    fireEvent.click(ttsInput);

    fireEvent.click(start());
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));
    fireEvent.click(stop());
    await waitFor(() => expect(socketInstances[0].sent.filter((payload) => String(payload).includes("stop_utterance"))).toHaveLength(1));

    fireEvent.click(start());
    await waitFor(() => expect(socketInstances[0].sent.filter((payload) => String(payload).includes("start_utterance"))).toHaveLength(2));

    const starts = socketInstances[0].sent.filter((payload) => String(payload).includes("start_utterance")).map(parseJsonMessage);
    expect(starts).toHaveLength(2);
    expect(starts[0].tts_enabled).toBe(true);
    expect(starts[1].tts_enabled).toBe(true);
    expect(starts[0].utterance_id).not.toBe(starts[1].utterance_id);
  });

  test("sends binary PCM chunks after audio capture", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    lastProcessor.onaudioprocess?.({
      inputBuffer: {
        getChannelData: () => new Float32Array([0, 0.25, -0.25, 0.5]),
      },
    } as unknown as AudioProcessingEvent);

    await waitFor(() => expect(socketInstances[0].sent.some((payload) => payload instanceof ArrayBuffer)).toBe(true));
  });

  test("continues sending PCM after backend reports speaking", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    socketInstances[0].emitJson({ type: "status", status: "speaking", muted: true });
    lastProcessor.onaudioprocess?.({
      inputBuffer: {
        getChannelData: () => new Float32Array([0, 0.25, -0.25, 0.5]),
      },
    } as unknown as AudioProcessingEvent);

    await waitFor(() => expect(socketInstances[0].sent.some((payload) => payload instanceof ArrayBuffer)).toBe(true));
  });

  test("does not start twice while start is in progress", async () => {
    const deferred = createDeferred<MediaStream>();
    getUserMedia.mockReturnValue(deferred.promise);
    renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    const start = screen.getByRole("button", { name: "开始说话" });
    fireEvent.click(start);
    fireEvent.click(start);

    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    deferred.resolve(makeStream());
    await waitFor(() => expect(socketInstances).toHaveLength(1));
  });

  test("does not send stop twice", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    const stop = screen.getByRole("button", { name: "停止说话" });
    fireEvent.click(stop);
    fireEvent.click(stop);

    expect(socketInstances[0].sent.filter((payload) => String(payload).includes("stop_utterance"))).toHaveLength(1);
  });

  test("handles voice_not_ready without adding chat messages and cleans resources", async () => {
    const onUserFinal = vi.fn();
    const onAgentReply = vi.fn();
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus, { onUserFinal, onAgentReply });

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    socketInstances[0].emitJson({
      type: "error",
      code: "voice_not_ready",
      message: "语音输入未就绪",
      status: { ...baseStatus, voiceEnabled: false, canRecord: false },
    });

    await waitFor(() => expect(lastTrackStop).toHaveBeenCalled());
    expect(socketInstances[0].close).toHaveBeenCalled();
    expect(onUserFinal).not.toHaveBeenCalled();
    expect(onAgentReply).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "开始说话" })).toBeDisabled();
  });

  test("final and agent_reply are surfaced without calling /api/chat", async () => {
    const onUserFinal = vi.fn();
    const onAgentReply = vi.fn();
    const fetchMock = renderWithStatus(readyStatus, { onUserFinal, onAgentReply }).fetchMock;

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    socketInstances[0].emitJson({ type: "final", utterance_id: "u1", text: "来一份黑椒牛肉饭" });
    socketInstances[0].emitJson({
      type: "agent_reply",
      utterance_id: "u1",
      text: "已加入一份黑椒牛肉饭",
      state: {},
      trace: {},
    });
    socketInstances[0].emitJson({
      type: "tts_status",
      utterance_id: "u1",
      source: "auto",
      queued: true,
      playbackTarget: "server",
    });

    expect(onUserFinal).toHaveBeenCalledWith("来一份黑椒牛肉饭");
    expect(onAgentReply).toHaveBeenCalledWith("已加入一份黑椒牛肉饭", {});
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/chat"), expect.anything());
    expect(voiceTtsQueueCalls(fetchMock)).toHaveLength(0);
    await waitFor(() => expect(screen.getByText(/已加入后端播报队列/)).toBeInTheDocument());
  });

  test("malformed WebSocket JSON shows an error and leaves recording state safe", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const onUserFinal = vi.fn();
    const onAgentReply = vi.fn();
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus, { onUserFinal, onAgentReply });

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    expect(() => socketInstances[0].emitRaw("{not-json")).not.toThrow();

    await waitFor(() => expect(screen.getByText(/语音服务返回了无法解析的消息/)).toBeInTheDocument());
    expect(lastTrackStop).toHaveBeenCalled();
    expect(socketInstances[0].close).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "停止说话" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "开始说话" })).toBeEnabled();
    expect(onUserFinal).not.toHaveBeenCalled();
    expect(onAgentReply).not.toHaveBeenCalled();
  });

  test("unknown WebSocket event types are ignored without crashing", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const onUserFinal = vi.fn();
    const onAgentReply = vi.fn();
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus, { onUserFinal, onAgentReply });

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    expect(() => socketInstances[0].emitJson({ type: "new_server_event", value: true })).not.toThrow();

    expect(screen.getByRole("button", { name: "停止说话" })).toBeEnabled();
    expect(screen.queryByText(/无法解析的消息/)).not.toBeInTheDocument();
    expect(onUserFinal).not.toHaveBeenCalled();
    expect(onAgentReply).not.toHaveBeenCalled();
  });

  test("voice debug emits structured truncated events when enabled", async () => {
    vi.stubEnv("VITE_DEBUG_VOICE", "true");
    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const onUserFinal = vi.fn();
    const onAgentReply = vi.fn();
    const fetchMock = renderWithStatus(readyStatus, { onUserFinal, onAgentReply }).fetchMock;
    getUserMedia.mockResolvedValue(makeStream());

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByLabelText("语音播报"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));
    const startPayload = parseJsonMessage(socketInstances[0].sent[0]);

    fireEvent.click(screen.getByRole("button", { name: "停止说话" }));
    await waitFor(() => expect(socketInstances[0].sent.filter((payload) => String(payload).includes("stop_utterance"))).toHaveLength(1));
    const longFinal = "012345678901234567890123456789-final-hidden";
    const longReply = "回复内容012345678901234567890123456789-hidden";
    socketInstances[0].emitJson({ type: "final", utterance_id: "u-debug", text: longFinal });
    socketInstances[0].emitJson({
      type: "agent_reply",
      utterance_id: "u-debug",
      text: longReply,
      state: { should: "not-log" },
      trace: { should: "not-log" },
    });
    socketInstances[0].emitJson({
      type: "tts_status",
      utterance_id: "u-debug",
      source: "auto",
      queued: true,
      job_id: 42,
      tts_enabled: true,
      playbackTarget: "server",
    });

    const startDebug = findDebugPayload(debugSpy, "start_utterance");
    const stopDebug = findDebugPayload(debugSpy, "stop_utterance");
    const finalDebug = findDebugPayload(debugSpy, "final");
    const replyDebug = findDebugPayload(debugSpy, "agent_reply");
    const ttsDebug = findDebugPayload(debugSpy, "tts_status");

    expect(startDebug).toMatchObject({
      session_id: "s1",
      event: "start_utterance",
      utterance_id: startPayload.utterance_id,
      tts_enabled: true,
    });
    expect(stopDebug).toMatchObject({
      session_id: "s1",
      event: "stop_utterance",
      utterance_id: startPayload.utterance_id,
    });
    expect(finalDebug).toMatchObject({
      session_id: "s1",
      event: "final",
      utterance_id: "u-debug",
      textLength: longFinal.length,
      preview: longFinal.slice(0, 30),
    });
    expect(replyDebug).toMatchObject({
      session_id: "s1",
      event: "agent_reply",
      utterance_id: "u-debug",
      textLength: longReply.length,
      preview: longReply.slice(0, 30),
    });
    expect(ttsDebug).toMatchObject({
      session_id: "s1",
      event: "tts_status",
      utterance_id: "u-debug",
      queued: true,
      reason: null,
      job_id: 42,
      tts_enabled: true,
    });
    expect(finalDebug).not.toHaveProperty("text");
    expect(replyDebug).not.toHaveProperty("trace");
    expect(String(finalDebug.preview)).not.toContain("hidden");
    expect(String(replyDebug.preview)).not.toContain("hidden");
    expect(onUserFinal).toHaveBeenCalledWith(longFinal);
    expect(onAgentReply).toHaveBeenCalledWith(longReply, { should: "not-log" });
    expect(voiceTtsQueueCalls(fetchMock)).toHaveLength(0);
  });

  test("voice debug is silent when disabled", async () => {
    vi.stubEnv("VITE_DEBUG_VOICE", "false");
    const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const onUserFinal = vi.fn();
    const onAgentReply = vi.fn();
    renderWithStatus(readyStatus, { onUserFinal, onAgentReply });
    getUserMedia.mockResolvedValue(makeStream());

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByLabelText("语音播报"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "停止说话" }));
    socketInstances[0].emitJson({ type: "final", utterance_id: "u-debug-off", text: "来一份饭" });
    socketInstances[0].emitJson({
      type: "agent_reply",
      utterance_id: "u-debug-off",
      text: "好的",
      state: {},
      trace: {},
    });
    socketInstances[0].emitJson({
      type: "tts_status",
      utterance_id: "u-debug-off",
      source: "auto",
      queued: true,
      job_id: 43,
      tts_enabled: true,
      playbackTarget: "server",
    });

    expect(debugSpy).not.toHaveBeenCalled();
    expect(onUserFinal).toHaveBeenCalledWith("来一份饭");
    expect(onAgentReply).toHaveBeenCalledWith("好的", {});
  });

  test("tts_status skip reason is shown without adding chat messages", async () => {
    const onUserFinal = vi.fn();
    const onAgentReply = vi.fn();
    renderWithStatus(readyStatus, { onUserFinal, onAgentReply });

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    socketInstances[0].emitJson({
      type: "tts_status",
      utterance_id: "u1",
      source: "auto",
      queued: false,
      reason: "user_tts_preference_off",
    });

    expect(await screen.findByText(/本轮未开启语音播报/)).toBeInTheDocument();
    expect(onUserFinal).not.toHaveBeenCalled();
    expect(onAgentReply).not.toHaveBeenCalled();
  });

  test("cleans microphone when WebSocket creation fails after getUserMedia", async () => {
    MockWebSocket.failOpen = true;
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));

    await waitFor(() => expect(lastTrackStop).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "开始说话" })).toBeEnabled();
  });

  test("does not show an error for expected close after stopping", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "停止说话" }));
    socketInstances[0].unexpectedClose();

    expect(screen.queryByText(/语音连接已断开/)).not.toBeInTheDocument();
    expect(lastProcessor.onaudioprocess).toBeNull();
    expect(lastProcessor.disconnect).toHaveBeenCalled();
    expect(lastSource.disconnect).toHaveBeenCalled();
    expect(lastSilentGain.disconnect).toHaveBeenCalled();
    expect(lastTrackStop).toHaveBeenCalled();
  });

  test("shows an error for unexpected close while recording", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    socketInstances[0].unexpectedClose();

    expect(await screen.findByText(/语音连接已断开/)).toBeInTheDocument();
    expect(lastTrackStop).toHaveBeenCalled();
  });

  test("refresh that makes canRecord false safely stops active recording", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    let voiceStatusCalls = 0;
    const fetchMock = vi.fn((url: string) => {
      if (url.includes("/voice/tts/status")) {
        return Promise.resolve(okJson(idleTtsStatus));
      }
      if (url.includes("/voice/status")) {
        voiceStatusCalls += 1;
        return Promise.resolve(okJson(voiceStatusCalls === 1 ? readyStatus : baseStatus));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VoiceControls sessionId="s1" onUserFinal={vi.fn()} onAgentReply={vi.fn()} />);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "刷新语音状态" }));

    await waitFor(() => expect(lastTrackStop).toHaveBeenCalled());
    expect(socketInstances[0].close).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "开始说话" })).toBeDisabled();
  });

  test("cleans resources on unmount and tolerates repeated cleanup", async () => {
    getUserMedia.mockResolvedValue(makeStream());
    const { unmount } = renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    unmount();
    unmount();

    expect(lastTrackStop).toHaveBeenCalled();
    expect(socketInstances[0].close).toHaveBeenCalled();
    expect(lastAudioClose).toHaveBeenCalled();
    expect(lastProcessor.onaudioprocess).toBeNull();
    expect(lastProcessor.disconnect).toHaveBeenCalled();
    expect(lastSource.disconnect).toHaveBeenCalled();
    expect(lastSilentGain.disconnect).toHaveBeenCalled();
  });

  test("disables TTS preference when canSpeak is false", async () => {
    renderWithStatus({ ...baseStatus, voiceEnabled: true, ttsEnabled: true, canSpeak: false });

    await screen.findByRole("button", { name: "开始说话" });
    expect(screen.getByLabelText("语音播报")).toBeDisabled();
    expect(screen.getByRole("button", { name: "测试播报" })).toBeDisabled();
  });

  test("test broadcast calls voice tts and then reads tts status without chat", async () => {
    const ttsStatus = {
      queueInitialized: true,
      speaking: false,
      queueSize: 0,
      maxQueueSize: 10,
      lastQueuedAt: "2026-05-25T00:00:00Z",
      lastStartedAt: "2026-05-25T00:00:01Z",
      lastFinishedAt: "2026-05-25T00:00:02Z",
      lastSuccess: true,
      lastError: null,
      lastTextLength: 11,
      lastTextPreview: "这是一条语音播报测试。",
      currentVoice: { id: "fake", name: "Fake Voice", languages: ["zh"] },
      playbackTarget: "server",
      currentDurationMs: 0,
      maybeStuck: false,
      lastSource: "manual",
    };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("/voice/status")) {
        return Promise.resolve(okJson(readyStatus));
      }
      if (url.includes("/voice/tts/status")) {
        return Promise.resolve(okJson(ttsStatus));
      }
      if (url.includes("/voice/tts")) {
        return Promise.resolve(okJson({ ok: true, queued: true, playbackTarget: "server" }));
      }
      if (url.includes("/chat")) {
        return Promise.resolve(okJson({}));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VoiceControls sessionId="s1" onUserFinal={vi.fn()} onAgentReply={vi.fn()} />);

    const testButton = await screen.findByRole("button", { name: "测试播报" });
    fireEvent.click(testButton);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/voice/tts"), expect.anything()));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/voice/tts/status")));
    expect(screen.getByText(/已加入后端播报队列/)).toBeInTheDocument();
    expect(screen.getByText(/lastSuccess=true|TTS 最近完成/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/chat"))).toBe(false);
  });

  test("shows interrupted TTS status without treating it as a failure", async () => {
    const fetchMock = renderWithTestBroadcastTtsStatus({
      ...idleTtsStatus,
      lastSuccess: false,
      lastError: "tts_interrupted",
      lastFinishedAt: "2026-05-25T00:00:02Z",
      currentVoice: { id: "fake", name: "Fake Voice", languages: ["zh"] },
    });

    fireEvent.click(await screen.findByRole("button", { name: "测试播报" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/voice/tts/status")));
    expect(await screen.findByText(/播报已被打断/)).toBeInTheDocument();
    expect(screen.queryByText(/最近失败/)).not.toBeInTheDocument();
  });

  test("shows real TTS errors as recent failures", async () => {
    const fetchMock = renderWithTestBroadcastTtsStatus({
      ...idleTtsStatus,
      lastSuccess: false,
      lastError: "tts_provider_error",
      lastFinishedAt: "2026-05-25T00:00:02Z",
      currentVoice: { id: "fake", name: "Fake Voice", languages: ["zh"] },
    });

    fireEvent.click(await screen.findByRole("button", { name: "测试播报" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/voice/tts/status")));
    expect(await screen.findByText(/TTS 最近失败.*tts_provider_error/)).toBeInTheDocument();
    expect(screen.queryByText(/播报已被打断/)).not.toBeInTheDocument();
  });

  test("empty ASR transcript message is not shown as a TTS failure", async () => {
    renderWithStatus(readyStatus);

    await screen.findByRole("button", { name: "开始说话" });
    fireEvent.click(screen.getByLabelText("语音输入"));
    fireEvent.click(screen.getByRole("button", { name: "开始说话" }));
    await waitFor(() => expect(socketInstances[0]?.sent).toHaveLength(1));

    socketInstances[0].emitJson({
      type: "tts_status",
      utterance_id: "u-empty",
      source: "auto",
      queued: false,
      reason: "ignored_empty_transcript",
    });

    expect(await screen.findByText(/本轮未识别到有效语音，因此没有触发新的回复播报/)).toBeInTheDocument();
    expect(screen.queryByText(/最近失败/)).not.toBeInTheDocument();
  });

  test("refresh only updates voice status controls", async () => {
    const fetchMock = renderWithStatus({ ...baseStatus, voiceEnabled: false, canRecord: false }).fetchMock;
    const refresh = await screen.findByRole("button", { name: "刷新语音状态" });

    fireEvent.click(refresh);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "开始说话" })).toBeDisabled();
  });
});

function renderWithStatus(
  status: unknown,
  handlers: { onUserFinal?: () => void; onAgentReply?: () => void } = {},
) {
  const fetchMock = vi.fn().mockResolvedValue(okJson(status));
  vi.stubGlobal("fetch", fetchMock);
  const renderResult = render(
    <VoiceControls
      sessionId="s1"
      onUserFinal={handlers.onUserFinal ?? vi.fn()}
      onAgentReply={handlers.onAgentReply ?? vi.fn()}
    />,
  );
  return { ...renderResult, fetchMock };
}

function renderWithTestBroadcastTtsStatus(ttsStatus: VoiceTtsStatus) {
  const fetchMock = vi.fn((url: string) => {
    if (url.includes("/voice/status")) {
      return Promise.resolve(okJson(readyStatus));
    }
    if (url.includes("/voice/tts/status")) {
      return Promise.resolve(okJson(ttsStatus));
    }
    if (url.includes("/voice/tts")) {
      return Promise.resolve(okJson({ ok: true, queued: true, playbackTarget: "server" }));
    }
    return Promise.resolve(okJson({}));
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<VoiceControls sessionId="s1" onUserFinal={vi.fn()} onAgentReply={vi.fn()} />);
  return fetchMock;
}

function okJson(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  };
}

function makeStream(): MediaStream {
  return {
    getTracks: () => [{ stop: lastTrackStop }],
  } as unknown as MediaStream;
}

function parseJsonMessage(payload: unknown): Record<string, unknown> {
  expect(typeof payload).toBe("string");
  return JSON.parse(payload as string) as Record<string, unknown>;
}

function findDebugPayload(debugSpy: { mock: { calls: unknown[][] } }, eventName: string): Record<string, unknown> {
  const call = debugSpy.mock.calls.find(([label]) => label === `[voice-debug] ${eventName}`);
  expect(call).toBeDefined();
  expect(call?.[1]).toEqual(expect.any(Object));
  return call?.[1] as Record<string, unknown>;
}

function voiceTtsQueueCalls(fetchMock: { mock: { calls: unknown[][] } }) {
  return fetchMock.mock.calls.filter(([url, init]) => {
    const request = init as RequestInit | undefined;
    return String(url).endsWith("/voice/tts") && request?.method === "POST";
  });
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

class MockAudioContext {
  state: AudioContextState = "running";
  audioWorklet = undefined;
  destination = lastDestination;
  sampleRate = 48000;
  createMediaStreamSource() {
    return lastSource;
  }
  createGain() {
    return lastSilentGain;
  }
  createScriptProcessor() {
    return lastProcessor;
  }
  close() {
    this.state = "closed";
    return lastAudioClose();
  }
}
