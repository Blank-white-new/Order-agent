import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { normalizeOrderState } from "../types/order";
import { SpeechReplayPanel } from "./SpeechReplayPanel";


const api = vi.hoisted(() => ({
  fetchSpeechFixtures: vi.fn(),
  runRepositoryFixture: vi.fn(),
  uploadSyntheticFixture: vi.fn(),
  fetchReplayTts: vi.fn(),
}));

vi.mock("../api/speechApi", () => api);

beforeEach(() => {
  vi.clearAllMocks();
  api.fetchSpeechFixtures.mockResolvedValue([{
    fixtureId: "audio-zh-004",
    locale: "zh-CN",
    outcome: "SUCCESS",
    contentType: "audio/wav",
    encoding: "WAV_PCM_S16LE",
    sampleRateHz: 16000,
    channels: 1,
    sampleWidthBytes: 2,
    synthetic: true,
  }]);
  api.runRepositoryFixture.mockResolvedValue({
    outcome: "SUCCESS",
    errorCode: null,
    response: "已加入草稿",
    state: normalizeOrderState({ lifecycle_status: "DRAFT", merchant_status: "NOT_INTEGRATED" }),
    trace: { multilingual: { canonicalIntent: "ADD_ITEM" } },
    detectedLocale: "zh-CN",
    responseLocale: "zh-CN",
    safetyClassification: "AUTO_DRAFT",
    handoffStatus: "NOT_REQUIRED",
    transcript: "我要一份鸡腿饭",
    confidence: 0.97,
    simulation: true,
    providerMode: "REPLAY",
    realSpeechRecognition: false,
    realSpeechSynthesis: false,
  });
});

describe("SpeechReplayPanel", () => {
  test("labels the control as offline replay and never as real recognition", async () => {
    render(<SpeechReplayPanel sessionId="synthetic-session" onOrderStateChange={vi.fn()} />);
    expect(screen.getByText("离线合成音频测试")).toBeInTheDocument();
    expect(screen.getByText(/不是真实语音识别/)).toBeInTheDocument();
    expect(screen.getByText(/不会请求麦克风/)).toBeInTheDocument();
    expect(screen.queryByText("真实语音识别成功")).not.toBeInTheDocument();
    expect(await screen.findByRole("option", { name: /audio-zh-004/ })).toBeInTheDocument();
  });

  test("shows transcript, confidence, locale, canonical intent and safety decision", async () => {
    const onOrderStateChange = vi.fn();
    render(
      <SpeechReplayPanel
        sessionId="synthetic-session"
        onOrderStateChange={onOrderStateChange}
      />,
    );
    await screen.findByRole("option", { name: /audio-zh-004/ });
    fireEvent.click(screen.getByRole("button", { name: "运行仓库 fixture" }));
    await waitFor(() => expect(api.runRepositoryFixture).toHaveBeenCalled());
    expect(await screen.findByText("我要一份鸡腿饭")).toBeInTheDocument();
    expect(screen.getByText("97%")).toBeInTheDocument();
    expect(screen.getByText("ADD_ITEM")).toBeInTheDocument();
    expect(screen.getByText("AUTO_DRAFT")).toBeInTheDocument();
    expect(screen.getByText("DRAFT / NOT_INTEGRATED")).toBeInTheDocument();
    expect(onOrderStateChange).toHaveBeenCalled();
  });
});
