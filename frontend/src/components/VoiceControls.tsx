import { useEffect, useRef, useState } from "react";
import {
  getVoiceStatus,
  getVoiceTtsStatus,
  getVoiceWebSocketUrl,
  postVoiceTts,
  postVoiceTtsStop,
  VoiceServerEvent,
  VoiceStatus,
  VoiceTtsStatus,
} from "../api/voiceApi";
import { normalizeOrderState, OrderStateView } from "../types/order";

type VoiceControlsProps = {
  sessionId: string;
  onUserFinal: (text: string) => void;
  onAgentReply: (text: string, trace: Record<string, unknown>) => void;
  onOrderStateChange?: (state: OrderStateView) => void;
  onTtsPreferenceChange?: (preference: { enabled: boolean; canSpeak: boolean }) => void;
};

type CleanupOptions = {
  closeSocket: boolean;
  resetRecording: boolean;
};

const TARGET_SAMPLE_RATE = 16000;
const VOICE_STATUS_FORMAT_ERROR = "语音状态响应格式异常。";
const VOICE_STATUS_REQUEST_ERROR = "无法获取后端语音状态。";
const VOICE_STATUS_LOADING = "正在检查后端语音状态…";
const VOICE_MESSAGE_PARSE_ERROR = "语音服务返回了无法解析的消息。";

export function VoiceControls({
  sessionId,
  onUserFinal,
  onAgentReply,
  onOrderStateChange,
  onTtsPreferenceChange,
}: VoiceControlsProps) {
  const debugVoiceEnabled = import.meta.env.VITE_DEBUG_VOICE === "true";
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [voiceInputPreference, setVoiceInputPreference] = useState(false);
  const [ttsPreference, setTtsPreference] = useState(false);
  const [statusText, setStatusText] = useState(VOICE_STATUS_LOADING);
  const [partial, setPartial] = useState("");
  const [voiceHint, setVoiceHint] = useState("");
  const [recording, setRecordingState] = useState(false);
  const [statusLoading, setStatusLoading] = useState(true);
  const [statusError, setStatusError] = useState(false);
  const [statusFormatInvalid, setStatusFormatInvalid] = useState(false);
  const [startingVoice, setStartingVoiceState] = useState(false);
  const [stoppingVoice, setStoppingVoiceState] = useState(false);
  const [testingTts, setTestingTts] = useState(false);
  const [ttsStatus, setTtsStatus] = useState<VoiceTtsStatus | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const processorRef = useRef<AudioWorkletNode | ScriptProcessorNode | null>(null);
  const silentGainRef = useRef<GainNode | null>(null);
  const utteranceIdRef = useRef<string>("");
  const shouldSendPcmRef = useRef(false);
  const pcmDebugLoggedRef = useRef(false);
  const recordingRef = useRef(false);
  const startingVoiceRef = useRef(false);
  const stoppingVoiceRef = useRef(false);
  const expectedSocketCloseRef = useRef(false);
  const isMountedRef = useRef(false);

  useEffect(() => {
    isMountedRef.current = true;
    void refreshVoiceStatus();
    return () => {
      isMountedRef.current = false;
      cleanupVoiceResources({ closeSocket: true, resetRecording: true });
    };
  }, []);

  function setRecording(next: boolean) {
    recordingRef.current = next;
    safeSetState(() => setRecordingState(next));
  }

  function setStartingVoice(next: boolean) {
    startingVoiceRef.current = next;
    safeSetState(() => setStartingVoiceState(next));
  }

  function setStoppingVoice(next: boolean) {
    stoppingVoiceRef.current = next;
    safeSetState(() => setStoppingVoiceState(next));
  }

  function safeSetState(update: () => void) {
    if (isMountedRef.current) {
      update();
    }
  }

  async function refreshVoiceStatus(): Promise<VoiceStatus | null> {
    safeSetState(() => {
      setStatusLoading(true);
      setStatusError(false);
      setStatusFormatInvalid(false);
      setVoiceHint("");
      setStatusText(VOICE_STATUS_LOADING);
    });
    try {
      const rawStatus = await getVoiceStatus();
      if (!isMountedRef.current) {
        return null;
      }
      const normalized = normalizeVoiceStatus(rawStatus);
      if (!normalized.ok) {
        safeSetState(() => {
          setVoiceStatus(null);
          setVoiceInputPreference(false);
          setTtsPreference(false);
          setStatusFormatInvalid(true);
          setStatusText(VOICE_STATUS_FORMAT_ERROR);
          setVoiceHint(VOICE_STATUS_FORMAT_ERROR);
        });
        publishTtsPreference(false, null);
        return null;
      }

      applyVoiceStatus(normalized.status);
      if (!normalized.status.canRecord && recordingRef.current) {
        cleanupVoiceResources({ closeSocket: true, resetRecording: true });
      }
      return normalized.status;
    } catch {
      safeSetState(() => {
        setVoiceStatus(null);
        setVoiceInputPreference(false);
        setTtsPreference(false);
        setStatusError(true);
        setStatusText(VOICE_STATUS_REQUEST_ERROR);
        setVoiceHint("无法获取后端语音状态。请确认 FastAPI 后端已启动，并检查 /api/voice/status 是否可访问。");
      });
      publishTtsPreference(false, null);
      return null;
    } finally {
      safeSetState(() => setStatusLoading(false));
    }
  }

  async function startVoice() {
    if (statusLoading) {
      safeSetState(() => setVoiceHint(VOICE_STATUS_LOADING));
      return;
    }
    if (statusError) {
      safeSetState(() => setVoiceHint("无法获取后端语音状态。请点击刷新语音状态重试。"));
      return;
    }
    if (statusFormatInvalid) {
      safeSetState(() => setVoiceHint(VOICE_STATUS_FORMAT_ERROR));
      return;
    }
    if (!voiceStatus) {
      safeSetState(() => setVoiceHint("正在检查后端语音状态，请稍后再试。"));
      return;
    }
    if (!voiceStatus.canRecord) {
      safeSetState(() => setVoiceHint(capabilityMessage(voiceStatus)));
      return;
    }
    if (!voiceInputPreference) {
      safeSetState(() => setVoiceHint("语音输入未启用。"));
      return;
    }
    if (recordingRef.current || startingVoiceRef.current || stoppingVoiceRef.current) {
      return;
    }

    setStartingVoice(true);
    safeSetState(() => {
      setVoiceHint("");
      setPartial("");
    });
    try {
      await stopTtsBeforeRecordingIfNeeded();
      await startMicrophone();
      const websocket = await ensureWebSocket();
      const utteranceId = crypto.randomUUID();
      utteranceIdRef.current = utteranceId;
      websocket.send(JSON.stringify({ type: "start_utterance", utterance_id: utteranceId, tts_enabled: ttsPreference }));
      debugVoice(debugVoiceEnabled, "start_utterance", {
        session_id: sessionId,
        event: "start_utterance",
        utterance_id: utteranceId,
        tts_enabled: ttsPreference,
      });
      shouldSendPcmRef.current = true;
      pcmDebugLoggedRef.current = false;
      setRecording(true);
      safeSetState(() => setStatusText("正在听"));
    } catch (err) {
      cleanupVoiceResources({ closeSocket: true, resetRecording: true });
      safeSetState(() => {
        setStatusText("错误");
        setVoiceHint(err instanceof Error ? err.message : "语音启动失败。");
      });
    } finally {
      setStartingVoice(false);
    }
  }

  async function stopTtsBeforeRecordingIfNeeded() {
    if (!voiceStatus?.canSpeak) {
      return;
    }
    let shouldStop = false;
    try {
      const status = await getVoiceTtsStatus();
      safeSetState(() => setTtsStatus(status));
      shouldStop = status.speaking || status.queueSize > 0;
    } catch (err) {
      shouldStop = true;
      console.warn("Voice TTS status check failed before recording; trying best-effort stop.", err);
    }
    if (!shouldStop) {
      return;
    }
    try {
      const result = await postVoiceTtsStop(sessionId);
      safeSetState(() => setTtsStatus(result.status));
    } catch (err) {
      console.warn("Voice TTS stop before recording failed.", err);
    }
  }

  function stopVoice() {
    if (!recordingRef.current || stoppingVoiceRef.current) {
      return;
    }
    setStoppingVoice(true);
    try {
      shouldSendPcmRef.current = false;
      const websocket = wsRef.current;
      if (websocket?.readyState === WebSocket.OPEN && utteranceIdRef.current) {
        const utteranceId = utteranceIdRef.current;
        websocket.send(JSON.stringify({ type: "stop_utterance", utterance_id: utteranceId }));
        debugVoice(debugVoiceEnabled, "stop_utterance", {
          session_id: sessionId,
          event: "stop_utterance",
          utterance_id: utteranceId,
        });
      }
      cleanupVoiceResources({ closeSocket: false, resetRecording: true });
      safeSetState(() => setStatusText("识别中"));
    } catch (err) {
      console.warn("Failed to stop voice utterance.", err);
      cleanupVoiceResources({ closeSocket: true, resetRecording: true });
    } finally {
      setStoppingVoice(false);
    }
  }

  async function testVoiceTts() {
    if (!voiceStatus?.canSpeak || testingTts) {
      return;
    }
    safeSetState(() => {
      setTestingTts(true);
      setVoiceHint("");
    });
    try {
      const response = await postVoiceTts("这是一条语音播报测试。", sessionId);
      if (response.queued) {
        safeSetState(() => setVoiceHint("已加入后端播报队列，请确认声音是否从运行 FastAPI 的机器播放。"));
      } else if (response.error === "ignored_empty_tts_text") {
        safeSetState(() => setVoiceHint("播报文本为空。"));
      } else {
        safeSetState(() => setVoiceHint(`测试播报未入队：${response.error ?? "unknown_error"}`));
      }
      const status = await getVoiceTtsStatus();
      safeSetState(() => setTtsStatus(status));
    } catch (err) {
      console.warn("Voice TTS test failed.", err);
      safeSetState(() => setVoiceHint("测试播报请求失败，请查看后端 TTS 状态或日志。"));
    } finally {
      safeSetState(() => setTestingTts(false));
    }
  }

  async function ensureWebSocket(): Promise<WebSocket> {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return wsRef.current;
    }
    expectedSocketCloseRef.current = false;
    const websocket = new WebSocket(getVoiceWebSocketUrl(sessionId));
    wsRef.current = websocket;
    websocket.onmessage = (event) => {
      if (!isMountedRef.current) {
        return;
      }
      const voiceEvent = parseVoiceServerEvent(event.data);
      if (voiceEvent === null) {
        handleMalformedVoiceMessage();
        return;
      }
      if (!voiceEvent) {
        console.warn("Ignored voice WebSocket message without a valid type.");
        return;
      }
      handleVoiceEvent(voiceEvent);
    };
    websocket.onclose = () => {
      if (wsRef.current === websocket) {
        wsRef.current = null;
      }
      shouldSendPcmRef.current = false;
      if (!isMountedRef.current || expectedSocketCloseRef.current) {
        return;
      }
      if (recordingRef.current || startingVoiceRef.current) {
        cleanupVoiceResources({ closeSocket: false, resetRecording: true });
        safeSetState(() => {
          setStatusText("错误");
          setVoiceHint("语音连接已断开，请重试。");
        });
      }
    };
    websocket.onerror = () => {
      if (!isMountedRef.current || expectedSocketCloseRef.current) {
        return;
      }
      if (recordingRef.current || startingVoiceRef.current) {
        cleanupVoiceResources({ closeSocket: true, resetRecording: true });
        safeSetState(() => {
          setStatusText("错误");
          setVoiceHint("语音连接已断开，请重试。");
        });
      }
    };
    return new Promise((resolve, reject) => {
      websocket.onopen = () => {
        if (!isMountedRef.current) {
          reject(new Error("语音控件已卸载。"));
          return;
        }
        resolve(websocket);
      };
      const originalError = websocket.onerror;
      websocket.onerror = (event) => {
        originalError?.call(websocket, event);
        reject(new Error("语音 WebSocket 连接失败。"));
      };
    });
  }

  function handleMalformedVoiceMessage() {
    cleanupVoiceResources({ closeSocket: true, resetRecording: true });
    setStartingVoice(false);
    setStoppingVoice(false);
    safeSetState(() => {
      setPartial("");
      setStatusText("错误");
      setVoiceHint(VOICE_MESSAGE_PARSE_ERROR);
    });
  }

  function handleVoiceEvent(event: VoiceServerEvent) {
    if (event.type === "status") {
      safeSetState(() => setStatusText(labelStatus(event.status)));
      shouldSendPcmRef.current = recordingRef.current;
      return;
    }
    if (event.type === "partial") {
      safeSetState(() => setPartial(event.text));
      return;
    }
    if (event.type === "final") {
      debugVoice(debugVoiceEnabled, "final", {
        session_id: sessionId,
        event: "final",
        utterance_id: event.utterance_id,
        textLength: event.text.length,
        preview: previewText(event.text),
      });
      safeSetState(() => setPartial(""));
      onUserFinal(event.text);
      return;
    }
    if (event.type === "agent_reply") {
      debugVoice(debugVoiceEnabled, "agent_reply", {
        session_id: sessionId,
        event: "agent_reply",
        utterance_id: event.utterance_id,
        textLength: event.text.length,
        preview: previewText(event.text),
      });
      onAgentReply(event.text, event.trace);
      if (isRecord(event.state)) {
        onOrderStateChange?.(normalizeOrderState(event.state));
      }
      return;
    }
    if (event.type === "tts_status") {
      debugVoice(debugVoiceEnabled, "tts_status", {
        session_id: sessionId,
        event: "tts_status",
        utterance_id: event.utterance_id,
        queued: event.queued,
        reason: event.reason ?? null,
        job_id: event.job_id ?? null,
        tts_enabled: event.tts_enabled,
      });
      if (event.queued) {
        safeSetState(() => setVoiceHint("已加入后端播报队列，请确认声音是否从运行 FastAPI 的机器播放。"));
      } else {
        const message = ttsReasonMessage(event.reason);
        if (event.reason !== "user_tts_preference_off") {
          console.warn(`Voice TTS skipped: ${event.reason}`);
        }
        safeSetState(() => setVoiceHint(message));
      }
      return;
    }
    if (event.type === "duplicate_utterance") {
      safeSetState(() => setStatusText("已忽略重复语音"));
      return;
    }
    if (event.type === "ignored_empty_transcript") {
      safeSetState(() => setStatusText("未识别到有效内容"));
      return;
    }
    if (event.type === "error") {
      if (event.code === "voice_not_ready") {
        const normalized = normalizeVoiceStatus(event.status);
        if (normalized.ok) {
          applyVoiceStatus(normalized.status);
        }
        cleanupVoiceResources({ closeSocket: true, resetRecording: true });
        setStartingVoice(false);
        setStoppingVoice(false);
        safeSetState(() => {
          setStatusText("错误");
          setVoiceHint(event.message || (normalized.ok ? capabilityMessage(normalized.status) : "语音输入未就绪。"));
        });
        return;
      }
      safeSetState(() => {
        setStatusText("错误");
        setVoiceHint(event.message);
      });
      return;
    }
    console.warn(`Ignored unknown voice WebSocket event type: ${String((event as { type?: unknown }).type)}`);
  }

  async function startMicrophone() {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    if (!isMountedRef.current) {
      stopTracks(stream);
      throw new Error("语音控件已卸载。");
    }
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const audioContext = new AudioContextClass();
    const source = audioContext.createMediaStreamSource(stream);
    streamRef.current = stream;
    audioContextRef.current = audioContext;
    sourceRef.current = source;

    if (audioContext.audioWorklet) {
      const workletUrl = URL.createObjectURL(
        new Blob(
          [
            `class VoicePcmProcessor extends AudioWorkletProcessor {
              process(inputs, outputs) {
                const input = inputs[0] && inputs[0][0];
                if (input) this.port.postMessage(input.slice(0));
                for (const output of outputs) {
                  for (const channel of output) channel.fill(0);
                }
                return true;
              }
            }
            registerProcessor("voice-pcm-processor", VoicePcmProcessor);`,
          ],
          { type: "application/javascript" },
        ),
      );
      await audioContext.audioWorklet.addModule(workletUrl);
      URL.revokeObjectURL(workletUrl);
      if (!isMountedRef.current) {
        throw new Error("语音控件已卸载。");
      }
      const node = new AudioWorkletNode(audioContext, "voice-pcm-processor");
      node.port.onmessage = (event) => {
        if (!isMountedRef.current) {
          return;
        }
        sendPcm(event.data as Float32Array, audioContext.sampleRate);
      };
      source.connect(node);
      processorRef.current = node;
    } else {
      // ScriptProcessorNode is kept only as a compatibility fallback for browsers without AudioWorklet.
      const node = audioContext.createScriptProcessor(4096, 1, 1);
      const silentGain = audioContext.createGain();
      silentGain.gain.value = 0;
      node.onaudioprocess = (event) => {
        try {
          if (isMountedRef.current) {
            sendPcm(event.inputBuffer.getChannelData(0), audioContext.sampleRate);
          }
        } finally {
          clearAudioOutput(event.outputBuffer);
        }
      };
      source.connect(node);
      node.connect(silentGain);
      silentGain.connect(audioContext.destination);
      processorRef.current = node;
      silentGainRef.current = silentGain;
    }
  }

  function cleanupVoiceResources({ closeSocket, resetRecording }: CleanupOptions) {
    shouldSendPcmRef.current = false;
    if (closeSocket) {
      expectedSocketCloseRef.current = true;
      const websocket = wsRef.current;
      wsRef.current = null;
      try {
        if (websocket && websocket.readyState !== WebSocket.CLOSED && websocket.readyState !== WebSocket.CLOSING) {
          websocket.close();
        }
      } catch (err) {
        console.warn("Failed to close voice WebSocket.", err);
      }
    }

    const processor = processorRef.current;
    if (processor && "onaudioprocess" in processor) {
      processor.onaudioprocess = null;
    }
    try {
      processor?.disconnect();
    } catch (err) {
      console.warn("Failed to disconnect voice processor.", err);
    }
    try {
      sourceRef.current?.disconnect();
    } catch (err) {
      console.warn("Failed to disconnect voice source.", err);
    }
    try {
      silentGainRef.current?.disconnect();
    } catch (err) {
      console.warn("Failed to disconnect voice silent gain.", err);
    }
    if (streamRef.current) {
      stopTracks(streamRef.current);
    }
    const audioContext = audioContextRef.current;
    if (audioContext && audioContext.state !== "closed") {
      try {
        void audioContext.close().catch((err) => console.warn("Failed to close voice audio context.", err));
      } catch (err) {
        console.warn("Failed to close voice audio context.", err);
      }
    }

    processorRef.current = null;
    sourceRef.current = null;
    silentGainRef.current = null;
    audioContextRef.current = null;
    streamRef.current = null;
    if (resetRecording) {
      setRecording(false);
    }
  }

  function sendPcm(input: Float32Array, sourceSampleRate: number) {
    const websocket = wsRef.current;
    if (!shouldSendPcmRef.current || websocket?.readyState !== WebSocket.OPEN) {
      return;
    }
    const pcm = floatTo16BitPcm(resample(input, sourceSampleRate, TARGET_SAMPLE_RATE));
    websocket.send(pcm);
    if (!pcmDebugLoggedRef.current) {
      pcmDebugLoggedRef.current = true;
    }
  }

  function applyVoiceStatus(nextStatus: VoiceStatus) {
    const nextTtsPreference = nextStatus.canSpeak ? ttsPreference : false;
    safeSetState(() => {
      setVoiceStatus(nextStatus);
      if (!nextStatus.canRecord) {
        setVoiceInputPreference(false);
      }
      if (!nextStatus.canSpeak) {
        setTtsPreference(false);
      }
      setStatusError(false);
      setStatusFormatInvalid(false);
      setStatusText(statusSummary(nextStatus));
      setVoiceHint(nextStatus.canRecord ? "" : capabilityMessage(nextStatus));
    });
    publishTtsPreference(nextTtsPreference, nextStatus);
  }

  function updateTtsPreference(next: boolean) {
    const enabled = next && Boolean(voiceStatus?.canSpeak);
    setTtsPreference(enabled);
    publishTtsPreference(enabled, voiceStatus);
  }

  function publishTtsPreference(enabled: boolean, status: VoiceStatus | null) {
    onTtsPreferenceChange?.({ enabled, canSpeak: Boolean(status?.canSpeak) });
  }

  const startDisabled =
    !voiceStatus?.canRecord ||
    !voiceInputPreference ||
    recording ||
    startingVoice ||
    stoppingVoice ||
    statusLoading ||
    statusError ||
    statusFormatInvalid;
  const stopDisabled = !recording || stoppingVoice;
  const testTtsDisabled = !voiceStatus?.canSpeak || statusLoading || statusError || statusFormatInvalid || testingTts;
  const bargeInHint =
    voiceInputPreference && ttsPreference && voiceStatus?.canRecord && voiceStatus.canSpeak
      ? "播报中也可以点击开始说话，系统会先停止当前播报，再录入本轮语音。"
      : "";

  return (
    <div className="voice-panel">
      <div className="voice-row">
        <label>
          <input
            type="checkbox"
            checked={voiceInputPreference}
            disabled={!voiceStatus?.canRecord || statusLoading || statusError || statusFormatInvalid}
            onChange={(event) => setVoiceInputPreference(event.target.checked && Boolean(voiceStatus?.canRecord))}
          />
          语音输入
        </label>
        <label>
          <input
            type="checkbox"
            checked={ttsPreference}
            disabled={!voiceStatus?.canSpeak || statusLoading || statusError || statusFormatInvalid}
            onChange={(event) => updateTtsPreference(event.target.checked)}
          />
          语音播报
        </label>
        <button type="button" className="voice-secondary-button" disabled={statusLoading} onClick={() => void refreshVoiceStatus()}>
          {statusLoading ? "刷新中…" : "刷新语音状态"}
        </button>
        <button
          type="button"
          className={`voice-secondary-button${testTtsDisabled ? " voice-button-disabled" : ""}`}
          disabled={testTtsDisabled}
          onClick={() => void testVoiceTts()}
        >
          {testingTts ? "测试中…" : "测试播报"}
        </button>
        <button
          type="button"
          className={`voice-primary-button${startDisabled ? " voice-button-disabled" : ""}`}
          disabled={startDisabled}
          onClick={startVoice}
        >
          {startingVoice ? "启动中…" : "开始说话"}
        </button>
        <button
          type="button"
          className={`voice-primary-button${stopDisabled ? " voice-button-disabled" : ""}`}
          disabled={stopDisabled}
          onClick={stopVoice}
        >
          {stoppingVoice ? "停止中…" : "停止说话"}
        </button>
      </div>
      <div className="voice-status-line">
        <span>后端语音：{backendLabel(voiceStatus, statusLoading, statusError, statusFormatInvalid)}</span>
        <span>ASR：{asrLabel(voiceStatus, statusLoading, statusError, statusFormatInvalid)}</span>
        <span>TTS：{ttsLabel(voiceStatus, statusLoading, statusError, statusFormatInvalid)}</span>
        <span>当前：{statusText}</span>
      </div>
      {voiceHint ? <p className="voice-hint">{voiceHint}</p> : bargeInHint ? <p className="voice-hint">{bargeInHint}</p> : null}
      {ttsStatus ? <p className="voice-tts-status">{formatTtsStatus(ttsStatus)}</p> : null}
      {partial ? <p className="partial">识别中：{partial}</p> : null}
      {voiceStatus ? (
        <details className="voice-diagnostics">
          <summary>诊断详情</summary>
          <dl>
            <dt>voiceEnabled</dt>
            <dd>{String(voiceStatus.voiceEnabled)}</dd>
            <dt>canRecord</dt>
            <dd>{String(voiceStatus.canRecord)}</dd>
            <dt>canSpeak</dt>
            <dd>{String(voiceStatus.canSpeak)}</dd>
            <dt>asrDependencyAvailable</dt>
            <dd>{String(voiceStatus.asrDependencyAvailable)}</dd>
            <dt>ttsDependencyAvailable</dt>
            <dd>{String(voiceStatus.ttsDependencyAvailable)}</dd>
            <dt>modelPathExists</dt>
            <dd>{String(voiceStatus.modelPathExists)}</dd>
            <dt>modelLooksValid</dt>
            <dd>{String(voiceStatus.modelLooksValid)}</dd>
            <dt>VOSK_MODEL_PATH</dt>
            <dd>{voiceStatus.voskModelPath}</dd>
            <dt>envFilePath</dt>
            <dd>{voiceStatus.envFilePath}</dd>
            <dt>disabledReason</dt>
            <dd>{voiceStatus.disabledReason ?? "-"}</dd>
            <dt>asrDisabledReason</dt>
            <dd>{voiceStatus.asrDisabledReason ?? "-"}</dd>
            <dt>ttsDisabledReason</dt>
            <dd>{voiceStatus.ttsDisabledReason ?? "-"}</dd>
            <dt>TTS Style</dt>
            <dd>{voiceStatus.ttsStyle ?? "-"}</dd>
            <dt>TTS Provider</dt>
            <dd>{voiceStatus.ttsProvider ?? "-"}</dd>
            <dt>TTS Rate</dt>
            <dd>{voiceStatus.ttsRate ?? "-"} wpm</dd>
            <dt>TTS Volume</dt>
            <dd>{voiceStatus.ttsVolume ?? "-"}</dd>
            <dt>TTS Voice (configured)</dt>
            <dd>{voiceStatus.ttsConfiguredVoice || "(auto-detect)"}</dd>
            <dt>TTS Pitch (configured)</dt>
            <dd>{voiceStatus.ttsConfiguredPitch ?? "-"}</dd>
            <dt>TTS Pitch (applied)</dt>
            <dd>{voiceStatus.ttsAppliedPitch ?? "null (not supported by pyttsx3)"}</dd>
            <dt>TTS Lang</dt>
            <dd>{voiceStatus.ttsLang ?? "-"}</dd>
            <dt>TTS Unsupported Params</dt>
            <dd>{voiceStatus.ttsUnsupportedParams?.join(", ") ?? "-"}</dd>
          </dl>
          {voiceStatus.hints.length ? <p>{voiceStatus.hints.join(" ")}</p> : null}
        </details>
      ) : null}
    </div>
  );
}

function normalizeVoiceStatus(raw: unknown): { ok: true; status: VoiceStatus } | { ok: false } {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return { ok: false };
  }
  const data = raw as Partial<VoiceStatus>;
  if (
    (data.voiceEnabled !== undefined && typeof data.voiceEnabled !== "boolean") ||
    (data.canRecord !== undefined && typeof data.canRecord !== "boolean") ||
    (data.canSpeak !== undefined && typeof data.canSpeak !== "boolean") ||
    (data.hints !== undefined && !Array.isArray(data.hints))
  ) {
    return { ok: false };
  }

  const status: VoiceStatus = {
    voiceEnabled: data.voiceEnabled ?? false,
    asrEngine: typeof data.asrEngine === "string" ? data.asrEngine : "vosk",
    ttsEnabled: typeof data.ttsEnabled === "boolean" ? data.ttsEnabled : false,
    ttsEngine: typeof data.ttsEngine === "string" ? data.ttsEngine : "pyttsx3",
    ttsPlaybackTarget: typeof data.ttsPlaybackTarget === "string" ? data.ttsPlaybackTarget : "server",
    ttsEngineRecreatePerTask: typeof data.ttsEngineRecreatePerTask === "boolean" ? data.ttsEngineRecreatePerTask : undefined,
    ttsStyle: typeof data.ttsStyle === "string" ? data.ttsStyle : undefined,
    ttsProvider: typeof data.ttsProvider === "string" ? data.ttsProvider : undefined,
    ttsRate: typeof data.ttsRate === "number" ? data.ttsRate : undefined,
    ttsVolume: typeof data.ttsVolume === "number" ? data.ttsVolume : undefined,
    ttsConfiguredPitch: typeof data.ttsConfiguredPitch === "number" ? data.ttsConfiguredPitch : undefined,
    ttsAppliedPitch: data.ttsAppliedPitch as number | null | undefined,
    ttsLang: typeof data.ttsLang === "string" ? data.ttsLang : undefined,
    ttsConfiguredVoice: typeof data.ttsConfiguredVoice === "string" ? data.ttsConfiguredVoice : undefined,
    ttsProviderCapabilities: data.ttsProviderCapabilities as VoiceStatus["ttsProviderCapabilities"],
    ttsUnsupportedParams: Array.isArray(data.ttsUnsupportedParams) ? (data.ttsUnsupportedParams as string[]) : undefined,
    asrReady: typeof data.asrReady === "boolean" ? data.asrReady : false,
    ttsReady: typeof data.ttsReady === "boolean" ? data.ttsReady : false,
    asrDependencyAvailable: typeof data.asrDependencyAvailable === "boolean" ? data.asrDependencyAvailable : false,
    ttsDependencyAvailable: typeof data.ttsDependencyAvailable === "boolean" ? data.ttsDependencyAvailable : false,
    modelPathExists: typeof data.modelPathExists === "boolean" ? data.modelPathExists : false,
    modelLooksValid: typeof data.modelLooksValid === "boolean" ? data.modelLooksValid : false,
    modelLoaded: typeof data.modelLoaded === "boolean" ? data.modelLoaded : false,
    canRecord: data.canRecord ?? false,
    canSpeak: data.canSpeak ?? false,
    asrDisabledReason: typeof data.asrDisabledReason === "string" ? data.asrDisabledReason : null,
    ttsDisabledReason: typeof data.ttsDisabledReason === "string" ? data.ttsDisabledReason : null,
    disabledReason: typeof data.disabledReason === "string" ? data.disabledReason : null,
    hints: (data.hints as string[] | undefined) ?? [],
    envFilePath: typeof data.envFilePath === "string" ? data.envFilePath : "",
    envFileExists: typeof data.envFileExists === "boolean" ? data.envFileExists : false,
    voskModelPath: typeof data.voskModelPath === "string" ? data.voskModelPath : "",
    error: typeof data.error === "string" ? data.error : null,
  };
  return { ok: true, status };
}

function stopTracks(stream: MediaStream) {
  for (const track of stream.getTracks()) {
    try {
      track.stop();
    } catch (err) {
      console.warn("Failed to stop voice media track.", err);
    }
  }
}

function clearAudioOutput(outputBuffer: AudioBuffer | undefined) {
  if (!outputBuffer) {
    return;
  }
  for (let index = 0; index < outputBuffer.numberOfChannels; index += 1) {
    outputBuffer.getChannelData(index).fill(0);
  }
}

function labelStatus(status: string) {
  const labels: Record<string, string> = {
    idle: "空闲",
    listening: "正在听",
    recognizing: "识别中",
    thinking: "思考中",
    speaking: "播放中",
    error: "错误",
  };
  return labels[status] ?? status;
}

function statusSummary(status: VoiceStatus) {
  if (!status.voiceEnabled) {
    return "后端语音未开启";
  }
  if (!status.canRecord) {
    return asrLabel(status, false, false, false);
  }
  return "语音输入已就绪";
}

function capabilityMessage(status: VoiceStatus | null) {
  if (!status) {
    return "正在检查后端语音状态，请稍后再试。";
  }
  if (!status.voiceEnabled) {
    return "后端语音功能未开启。请在后端 .env 设置 VOICE_ENABLED=true，并重启 FastAPI 后端。";
  }
  if (!status.modelPathExists) {
    return "ASR 模型路径不存在，请检查后端 VOSK_MODEL_PATH。";
  }
  if (!status.modelLooksValid) {
    return "ASR 模型目录结构无效，请确认 VOSK_MODEL_PATH 指向解压后的 Vosk 模型目录。";
  }
  if (!status.asrDependencyAvailable) {
    return "ASR 依赖缺失：未安装 vosk。";
  }
  return status.disabledReason ?? status.asrDisabledReason ?? "当前语音输入不可用。";
}

function ttsReasonMessage(reason: string | undefined) {
  const messages: Record<string, string> = {
    user_tts_preference_off: "本轮未开启语音播报。",
    tts_disabled: "后端 TTS 未开启。",
    can_speak_false: "后端语音播报不可用。",
    empty_text: "播报文本为空。",
    tts_queue_full: "后端播报队列已满。",
    tts_queue_stuck: "后端播报队列可能卡住。",
    duplicate_utterance: "重复语音轮次未播报。",
    ignored_empty_transcript: "本轮未识别到有效语音，因此没有触发新的回复播报。",
    tts_error: "后端播报入队失败。",
  };
  return messages[reason ?? ""] ?? "语音播报未入队。";
}

function formatTtsStatus(status: VoiceTtsStatus) {
  const voiceName = status.currentVoice?.name ?? "default";
  if (status.speaking) {
    return `TTS 正在播报，voice=${voiceName}，duration=${status.currentDurationMs}ms，maybeStuck=${status.maybeStuck}`;
  }
  if (status.lastSuccess === true) {
    return `TTS 最近完成，lastSuccess=true，voice=${voiceName}，finished=${status.lastFinishedAt ?? "-"}`;
  }
  if (status.lastSuccess === false) {
    if (status.lastError === "tts_interrupted") {
      return `TTS 最近一次播报已被打断，lastError=${status.lastError}，voice=${voiceName}`;
    }
    return `TTS 最近失败，lastError=${status.lastError ?? "-"}，voice=${voiceName}`;
  }
  return `TTS 状态：queueInitialized=${status.queueInitialized}，queueSize=${status.queueSize}，lastSource=${status.lastSource ?? "-"}`;
}

function backendLabel(status: VoiceStatus | null, loading: boolean, failed: boolean, invalid: boolean) {
  if (loading) {
    return "检查中";
  }
  if (failed) {
    return "状态未知";
  }
  if (invalid) {
    return "格式异常";
  }
  return status?.voiceEnabled ? "已开启" : "未开启";
}

function asrLabel(status: VoiceStatus | null, loading: boolean, failed: boolean, invalid: boolean) {
  if (loading) {
    return "检查中";
  }
  if (failed) {
    return "状态未知";
  }
  if (invalid) {
    return "格式异常";
  }
  if (!status?.voiceEnabled) {
    return "未启用";
  }
  if (!status.modelPathExists) {
    return "模型路径不存在";
  }
  if (!status.modelLooksValid) {
    return "模型目录结构无效";
  }
  if (!status.asrDependencyAvailable) {
    return "依赖缺失";
  }
  return status.canRecord ? "已就绪" : "未就绪";
}

function ttsLabel(status: VoiceStatus | null, loading: boolean, failed: boolean, invalid: boolean) {
  if (loading) {
    return "检查中";
  }
  if (failed) {
    return "状态未知";
  }
  if (invalid) {
    return "格式异常";
  }
  if (!status?.voiceEnabled || !status.ttsEnabled) {
    return "未启用";
  }
  if (!status.ttsDependencyAvailable) {
    return "依赖缺失";
  }
  if (status.canSpeak && status.ttsPlaybackTarget === "server") {
    return "已就绪，后端本机播放";
  }
  return status.canSpeak ? "已就绪" : "未就绪";
}

function resample(input: Float32Array, sourceRate: number, targetRate: number): Float32Array {
  if (sourceRate === targetRate) {
    return input;
  }
  const ratio = sourceRate / targetRate;
  const outputLength = Math.floor(input.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i += 1) {
    output[i] = input[Math.floor(i * ratio)] ?? 0;
  }
  return output;
}

function floatTo16BitPcm(input: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(input.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < input.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return buffer;
}

function previewText(text: string) {
  return text.slice(0, 30);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseVoiceServerEvent(data: unknown): VoiceServerEvent | null | undefined {
  try {
    const parsed = JSON.parse(String(data)) as unknown;
    if (!parsed || typeof parsed !== "object" || typeof (parsed as { type?: unknown }).type !== "string") {
      return undefined;
    }
    return parsed as VoiceServerEvent;
  } catch (err) {
    console.warn("Failed to parse voice WebSocket message.", err);
    return null;
  }
}

function debugVoice(enabled: boolean, eventName: string, fields: Record<string, unknown>) {
  if (enabled) {
    console.debug(`[voice-debug] ${eventName}`, fields);
  }
}

declare global {
  interface Window {
    webkitAudioContext?: typeof AudioContext;
  }
}
