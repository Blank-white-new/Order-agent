const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export type VoiceStatus = {
  voiceEnabled: boolean;
  asrEngine: string;
  ttsEnabled: boolean;
  ttsEngine: string;
  ttsPlaybackTarget: string;
  ttsEngineRecreatePerTask?: boolean;
  ttsStyle?: string;
  ttsProvider?: string;
  ttsRate?: number;
  ttsVolume?: number;
  ttsConfiguredPitch?: number;
  ttsAppliedPitch?: number | null;
  ttsLang?: string;
  ttsConfiguredVoice?: string;
  ttsProviderCapabilities?: ProviderCapabilities;
  ttsUnsupportedParams?: string[];
  asrReady: boolean;
  ttsReady: boolean;
  asrDependencyAvailable: boolean;
  ttsDependencyAvailable: boolean;
  modelPathExists: boolean;
  modelLooksValid: boolean;
  modelLoaded: boolean;
  canRecord: boolean;
  canSpeak: boolean;
  asrDisabledReason?: string | null;
  ttsDisabledReason?: string | null;
  disabledReason?: string | null;
  hints: string[];
  envFilePath: string;
  envFileExists: boolean;
  voskModelPath: string;
  error?: string | null;
};

export type ProviderCapabilities = {
  voice: boolean;
  rate: boolean;
  volume: boolean;
  pitch: boolean;
};

export type VoiceTtsEffectiveConfig = {
  style: string;
  rate: number;
  volume: number;
  configuredPitch: number;
  appliedPitch: number | null;
  lang: string;
  provider: string;
};

export type VoiceServerEvent =
  | { type: "status"; status: string; muted?: boolean; utterance_id?: string }
  | { type: "partial"; text: string }
  | { type: "final"; utterance_id: string; text: string }
  | { type: "agent_reply"; utterance_id: string; text: string; state?: unknown; trace: Record<string, unknown> }
  | {
      type: "tts_status";
      utterance_id: string;
      source: "auto";
      queued: boolean;
      job_id?: number | null;
      playbackTarget?: string;
      tts_enabled?: boolean;
      reason?:
        | "user_tts_preference_off"
        | "tts_disabled"
        | "can_speak_false"
        | "empty_text"
        | "tts_queue_full"
        | "tts_queue_stuck"
        | "duplicate_utterance"
        | "ignored_empty_transcript"
        | "tts_error"
        | "runner_shutdown";
    }
  | { type: "duplicate_utterance"; utterance_id: string; ignored: true }
  | { type: "ignored_empty_transcript"; utterance_id: string; ignored: true }
  | { type: "error"; message: string; code?: string; status?: VoiceStatus };

export type VoiceTtsJob = {
  jobId: number;
  source: "auto" | "manual";
  status: "queued" | "running" | "success" | "failed" | "interrupted";
  success: boolean | null;
  error: string | null;
  queuedAt: string | null;
  startedAt: string | null;
  initStartedAt?: string | null;
  initFinishedAt?: string | null;
  runAndWaitStartedAt?: string | null;
  runAndWaitFinishedAt?: string | null;
  finishedAt: string | null;
  textLength: number;
  preview?: string;
};

export type VoiceTtsStatus = {
  queueInitialized: boolean;
  speaking: boolean;
  queueSize: number;
  maxQueueSize: number;
  lastQueuedAt: string | null;
  lastStartedAt: string | null;
  lastFinishedAt: string | null;
  lastSuccess: boolean | null;
  lastError: string | null;
  lastErrorAt?: string | null;
  lastTextLength: number;
  lastTextPreview: string | null;
  currentVoice: { id: string | null; name: string | null; languages: string[] };
  playbackTarget: string;
  currentDurationMs: number;
  maybeStuck: boolean;
  lastSource: "auto" | "manual" | null;
  workerAlive?: boolean;
  workerRestartCount?: number;
  jobsQueued?: number;
  jobsStarted?: number;
  jobsFinished?: number;
  jobsInterrupted?: number;
  totalSuccesses?: number;
  totalFailures?: number;
  lastJobId?: number | null;
  lastQueuedJobId?: number | null;
  lastStartedJobId?: number | null;
  lastFinishedJobId?: number | null;
  lastDequeuedAt?: string | null;
  lastInitStartedAt?: string | null;
  lastInitFinishedAt?: string | null;
  lastRunAndWaitStartedAt?: string | null;
  lastRunAndWaitFinishedAt?: string | null;
  lastStoppedAt?: string | null;
  lastInterruptedAt?: string | null;
  jobHistory?: VoiceTtsJob[];
  latestManualJob?: VoiceTtsJob | null;
  latestAutoJob?: VoiceTtsJob | null;
  enabled?: boolean;
  requestedProvider?: string;
  resolvedProvider?: string;
  providerFallbackReason?: string | null;
  provider?: string;
  style?: string;
  configuredVoice?: string;
  resolvedVoice?: string | null;
  resolvedVoiceAvailable?: boolean;
  resolvedVoiceUnavailableReason?: string | null;
  voiceFallbackReason?: string | null;
  rate?: number;
  volume?: number;
  configuredPitch?: number;
  appliedPitch?: number | null;
  lang?: string;
  legacyConfigUsed?: boolean;
  providerCapabilities?: ProviderCapabilities;
  unsupportedParams?: string[];
  effectiveConfig?: VoiceTtsEffectiveConfig;
  lastJobStatus?: string | null;
  updatedAt?: string | null;
  runtimeId?: string;
  runnerId?: number | null;
};

export type VoiceTtsResponse = {
  ok: boolean;
  queued?: boolean;
  job_id?: number | null;
  ignored?: boolean;
  error?: string;
  playbackTarget: string;
};

export type VoiceTtsStopResponse = {
  ok: boolean;
  stopped: boolean;
  interrupted: boolean;
  clearedJobs: number;
  status: VoiceTtsStatus;
};

export async function getVoiceStatus(): Promise<VoiceStatus> {
  const response = await fetch(`${API_BASE}/voice/status`);
  if (!response.ok) {
    throw new Error("voice status request failed");
  }
  return response.json();
}

export function getVoiceWebSocketUrl(sessionId: string): string {
  const apiUrl = new URL(API_BASE, window.location.href);
  apiUrl.protocol = apiUrl.protocol === "https:" ? "wss:" : "ws:";
  apiUrl.pathname = `${apiUrl.pathname.replace(/\/$/, "")}/voice/asr`;
  apiUrl.search = `session_id=${encodeURIComponent(sessionId)}`;
  return apiUrl.toString();
}

export async function postVoiceTts(text: string, sessionId: string): Promise<VoiceTtsResponse> {
  const response = await fetch(`${API_BASE}/voice/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, session_id: sessionId }),
  });
  if (!response.ok) {
    throw new Error("voice tts request failed");
  }
  return response.json();
}

export async function getVoiceTtsStatus(): Promise<VoiceTtsStatus> {
  const response = await fetch(`${API_BASE}/voice/tts/status`);
  if (!response.ok) {
    throw new Error("voice tts status request failed");
  }
  return response.json();
}

export async function postVoiceTtsStop(sessionId: string): Promise<VoiceTtsStopResponse> {
  const response = await fetch(`${API_BASE}/voice/tts/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) {
    throw new Error("voice tts stop request failed");
  }
  return response.json();
}
