import { normalizeOrderState, OrderStateView } from "../types/order";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export type ReplayFixture = {
  fixtureId: string;
  locale: string;
  outcome: string;
  contentType: string;
  encoding: "WAV_PCM_S16LE";
  sampleRateHz: number;
  channels: number;
  sampleWidthBytes: number;
  synthetic: true;
};

export type ReplaySpeechResult = {
  outcome: string;
  errorCode: string | null;
  response: string | null;
  state: OrderStateView;
  trace: Record<string, unknown>;
  detectedLocale: string | null;
  responseLocale: string | null;
  safetyClassification: string | null;
  handoffStatus: string | null;
  transcript: string | null;
  confidence: number | null;
  simulation: true;
  providerMode: "REPLAY";
  realSpeechRecognition: false;
  realSpeechSynthesis: false;
};

export async function fetchSpeechFixtures(): Promise<ReplayFixture[]> {
  const response = await fetch(`${API_BASE}/speech/fixtures`);
  if (!response.ok) {
    throw new Error("synthetic fixture catalog unavailable");
  }
  const body = (await response.json()) as { fixtures?: ReplayFixture[] };
  return Array.isArray(body.fixtures) ? body.fixtures : [];
}

export async function runRepositoryFixture(
  fixture: ReplayFixture,
  sessionId: string,
): Promise<ReplaySpeechResult> {
  const fixtureResponse = await fetch(
    `${API_BASE}/speech/fixtures/${encodeURIComponent(fixture.fixtureId)}/audio`,
  );
  if (!fixtureResponse.ok) {
    throw new Error("synthetic fixture audio unavailable");
  }
  return postSyntheticAudio(await fixtureResponse.blob(), fixture, sessionId);
}

export async function uploadSyntheticFixture(
  file: File,
  fixture: ReplayFixture,
  sessionId: string,
): Promise<ReplaySpeechResult> {
  return postSyntheticAudio(file, fixture, sessionId);
}

async function postSyntheticAudio(
  body: Blob,
  fixture: ReplayFixture,
  sessionId: string,
): Promise<ReplaySpeechResult> {
  const response = await fetch(`${API_BASE}/speech/respond`, {
    method: "POST",
    headers: {
      "Content-Type": fixture.contentType,
      "X-Fixture-Id": fixture.fixtureId,
      "X-Session-Id": sessionId,
      "X-Restaurant-Code": "hk-sim-restaurant-a",
      "X-Branch-Code": "central",
      "X-Audio-Encoding": fixture.encoding,
      "X-Sample-Rate-Hz": String(fixture.sampleRateHz),
      "X-Channels": String(fixture.channels),
      "X-Sample-Width-Bytes": String(fixture.sampleWidthBytes),
    },
    body,
  });
  if (!response.ok) {
    const error = (await response.json().catch(() => null)) as { error?: { code?: string } } | null;
    throw new Error(error?.error?.code ?? "synthetic speech request failed");
  }
  const payload = (await response.json()) as Record<string, unknown>;
  const transcriptMetadata = record(payload.transcriptMetadata);
  return {
    outcome: stringValue(payload.outcome) ?? "PROVIDER_ERROR",
    errorCode: stringValue(payload.errorCode),
    response: stringValue(payload.response),
    state: normalizeOrderState(payload.state),
    trace: record(payload.trace),
    detectedLocale: stringValue(payload.detectedLocale),
    responseLocale: stringValue(payload.responseLocale),
    safetyClassification: stringValue(payload.safetyClassification),
    handoffStatus: stringValue(payload.handoffStatus),
    transcript: stringValue(transcriptMetadata.transcript),
    confidence: numberValue(transcriptMetadata.confidence),
    simulation: true,
    providerMode: "REPLAY",
    realSpeechRecognition: false,
    realSpeechSynthesis: false,
  };
}

export async function fetchReplayTts(
  text: string,
  locale: string,
  sessionId: string,
): Promise<Blob> {
  const response = await fetch(`${API_BASE}/speech/synthesize`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-Id": sessionId,
      "X-Restaurant-Code": "hk-sim-restaurant-a",
      "X-Branch-Code": "central",
    },
    body: JSON.stringify({
      text,
      locale,
      voiceId: "replay-neutral",
      outputEncoding: "WAV_PCM_S16LE",
      sampleRateHz: 16000,
    }),
  });
  if (!response.ok || response.headers.get("X-Provider-Mode") !== "REPLAY") {
    throw new Error("replay TTS fixture unavailable");
  }
  return response.blob();
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
