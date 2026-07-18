import { ChangeEvent, useEffect, useMemo, useState } from "react";
import {
  fetchReplayTts,
  fetchSpeechFixtures,
  ReplayFixture,
  ReplaySpeechResult,
  runRepositoryFixture,
  uploadSyntheticFixture,
} from "../api/speechApi";
import { OrderStateView } from "../types/order";

type Props = {
  sessionId: string;
  onOrderStateChange: (state: OrderStateView) => void;
};

const TTS_EXAMPLE: Record<string, string> = {
  "zh-CN": "尚未发送给真实餐厅",
  "yue-Hant-HK": "尚未傳送俾真實餐廳",
  "en-HK": "The order has not been sent to a real restaurant.",
};

export function SpeechReplayPanel({ sessionId, onOrderStateChange }: Props) {
  const [fixtures, setFixtures] = useState<ReplayFixture[]>([]);
  const [fixtureId, setFixtureId] = useState("");
  const [upload, setUpload] = useState<File | null>(null);
  const [result, setResult] = useState<ReplaySpeechResult | null>(null);
  const [status, setStatus] = useState("正在加载 synthetic fixture…");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    void fetchSpeechFixtures()
      .then((values) => {
        if (!active) return;
        const visible = values.filter((value) => value.outcome === "SUCCESS").slice(0, 24);
        setFixtures(visible);
        setFixtureId(visible[0]?.fixtureId ?? "");
        setStatus(visible.length ? "可运行仓库内离线 fixture" : "没有可用 fixture");
      })
      .catch(() => active && setStatus("语音模拟端点未启用"));
    return () => {
      active = false;
    };
  }, []);

  const selected = useMemo(
    () => fixtures.find((fixture) => fixture.fixtureId === fixtureId) ?? null,
    [fixtureId, fixtures],
  );
  const canonicalIntent = nestedString(result?.trace, "multilingual", "canonicalIntent");

  async function execute(useUpload: boolean) {
    if (!selected || (useUpload && !upload) || busy) return;
    setBusy(true);
    setStatus("正在运行离线 Replay 管线…");
    try {
      const next = useUpload
        ? await uploadSyntheticFixture(upload as File, selected, sessionId)
        : await runRepositoryFixture(selected, sessionId);
      setResult(next);
      onOrderStateChange(next.state);
      setStatus("离线 Replay 管线完成");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Replay 管线失败");
    } finally {
      setBusy(false);
    }
  }

  function onUpload(event: ChangeEvent<HTMLInputElement>) {
    setUpload(event.target.files?.[0] ?? null);
  }

  async function playTts() {
    const locale = result?.responseLocale ?? selected?.locale ?? "zh-CN";
    const concrete = locale === "mixed" ? "zh-CN" : locale;
    setBusy(true);
    try {
      const blob = await fetchReplayTts(TTS_EXAMPLE[concrete] ?? TTS_EXAMPLE["zh-CN"], concrete, sessionId);
      const url = URL.createObjectURL(blob);
      const player = new Audio(url);
      player.addEventListener("ended", () => URL.revokeObjectURL(url), { once: true });
      await player.play();
      setStatus("正在播放预制 Replay TTS fixture（不是真实 TTS）");
    } catch {
      setStatus("Replay TTS fixture 播放失败；订单状态未改变");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel speech-replay-panel" aria-labelledby="speech-replay-title">
      <div className="panel-heading">
        <div>
          <h2 id="speech-replay-title">离线合成音频测试</h2>
          <p>Replay Provider · 不是真实语音识别 · 未连接真实电话或餐厅</p>
        </div>
        <span className="status-pill warning">SIMULATION</span>
      </div>
      <p className="speech-replay-warning">
        仅使用 synthetic WAV fixture；此界面不会请求麦克风，也不证明真实 ASR/TTS 准确率。
      </p>
      <label htmlFor="speech-fixture">仓库 fixture</label>
      <select
        id="speech-fixture"
        value={fixtureId}
        onChange={(event) => setFixtureId(event.target.value)}
      >
        {fixtures.map((fixture) => (
          <option value={fixture.fixtureId} key={fixture.fixtureId}>
            {fixture.fixtureId} · {fixture.locale} · {fixture.sampleRateHz} Hz
          </option>
        ))}
      </select>
      <div className="speech-replay-actions">
        <button type="button" disabled={!selected || busy} onClick={() => void execute(false)}>
          运行仓库 fixture
        </button>
        <label className="speech-upload">
          上传 synthetic WAV
          <input type="file" accept="audio/wav,.wav" onChange={onUpload} />
        </label>
        <button type="button" disabled={!selected || !upload || busy} onClick={() => void execute(true)}>
          校验并运行上传文件
        </button>
        <button type="button" disabled={!selected || busy} onClick={() => void playTts()}>
          播放 Replay TTS 安全示例
        </button>
      </div>
      <p role="status">{status}</p>
      {result ? (
        <dl className="speech-replay-result">
          <dt>Transcript</dt><dd>{result.transcript ?? "not returned"}</dd>
          <dt>ASR confidence</dt><dd>{result.confidence === null ? "missing" : `${(result.confidence * 100).toFixed(0)}%`}</dd>
          <dt>Detected locale</dt><dd>{result.detectedLocale ?? "und"}</dd>
          <dt>Canonical intent</dt><dd>{canonicalIntent ?? "not evaluated"}</dd>
          <dt>SafetyDecision</dt><dd>{result.safetyClassification ?? "not evaluated"}</dd>
          <dt>Speech outcome</dt><dd>{result.outcome}</dd>
          <dt>Order result</dt><dd>{result.state.lifecycleStatus} / {result.state.merchantStatus}</dd>
        </dl>
      ) : null}
    </section>
  );
}

function nestedString(
  value: Record<string, unknown> | undefined,
  parent: string,
  child: string,
): string | null {
  const nested = value?.[parent];
  if (typeof nested !== "object" || nested === null || Array.isArray(nested)) return null;
  const candidate = (nested as Record<string, unknown>)[child];
  return typeof candidate === "string" ? candidate : null;
}
