import { afterEach, describe, expect, test, vi } from "vitest";
import {
  fetchSpeechFixtures,
  ReplayFixture,
  runRepositoryFixture,
} from "./speechApi";


afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const fixture: ReplayFixture = {
  fixtureId: "audio-zh-004",
  locale: "zh-CN",
  outcome: "SUCCESS",
  contentType: "audio/wav",
  encoding: "WAV_PCM_S16LE",
  sampleRateHz: 16000,
  channels: 1,
  sampleWidthBytes: 2,
  synthetic: true,
};

describe("speechApi", () => {
  test("loads only explicit replay fixture metadata", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({
      ok: true,
      json: async () => ({ fixtures: [fixture], providerMode: "REPLAY", simulation: true }),
    })));
    expect(await fetchSpeechFixtures()).toEqual([fixture]);
  });

  test("downloads repository audio then posts bytes with controlled metadata", async () => {
    const audio = new Blob([new Uint8Array([82, 73, 70, 70])], { type: "audio/wav" });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, blob: async () => audio })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          outcome: "SUCCESS",
          response: "已加入草稿",
          state: { lifecycle_status: "DRAFT", merchant_status: "NOT_INTEGRATED" },
          trace: { multilingual: { canonicalIntent: "ADD_ITEM" } },
          detectedLocale: "zh-CN",
          responseLocale: "zh-CN",
          safetyClassification: "AUTO_DRAFT",
          handoffStatus: "NOT_REQUIRED",
          transcriptMetadata: { transcript: "我要一份鸡腿饭", confidence: 0.97 },
        }),
      });
    vi.stubGlobal("fetch", fetchMock);
    const result = await runRepositoryFixture(fixture, "synthetic-session");
    expect(result.transcript).toBe("我要一份鸡腿饭");
    expect(result.state.merchantStatus).toBe("NOT_INTEGRATED");
    const request = fetchMock.mock.calls[1][1] as RequestInit;
    expect(request.body).toBe(audio);
    expect(request.headers).toMatchObject({
      "X-Fixture-Id": fixture.fixtureId,
      "X-Audio-Encoding": "WAV_PCM_S16LE",
      "X-Session-Id": "synthetic-session",
    });
  });
});
