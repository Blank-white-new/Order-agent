import { useEffect, useState } from "react";
import {
  cancelHandoff,
  HandoffView,
  simulateAssign,
  simulateConnect,
  simulateFail,
  simulateResolve,
} from "../api/handoffApi";
import { OrderStateView } from "../types/order";
import { ConcreteLocale } from "../i18n";

type Props = {
  sessionId: string;
  state: OrderStateView;
  onStatusChange?: (status: string) => void;
  locale?: ConcreteLocale;
};

const DEVELOPMENT_CONTROLS = import.meta.env.DEV || import.meta.env.MODE === "test";

export function SafetyHandoffPanel({ sessionId, state, onStatusChange, locale = "zh-CN" }: Props) {
  const copy = SAFETY_COPY[locale];
  const [status, setStatus] = useState(state.handoffStatus);
  const [failureCode, setFailureCode] = useState<string | null>(null);
  const [cancellation, setCancellation] = useState<HandoffView | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setStatus(state.handoffStatus);
    setCancellation(null);
  }, [state.handoffStatus, state.handoffPublicId]);

  async function run(operation: (publicId: string, sessionId: string) => Promise<HandoffView>) {
    if (!state.handoffPublicId || pending) {
      return;
    }
    setPending(true);
    setError(null);
    try {
      const result = await operation(state.handoffPublicId, sessionId);
      setStatus(result.status);
      setFailureCode(result.failureCode);
      setCancellation(result.status === "CANCELLED" ? result : null);
      onStatusChange?.(result.status);
    } catch {
      setError(copy.operationFailed);
    } finally {
      setPending(false);
    }
  }

  const handoff = state.safetyClassification === "HANDOFF";
  const refused = state.safetyClassification === "REFUSE";
  const explicitCancellation = status === "CANCELLED"
    && (cancellation?.mayContinueDraft ?? state.safetyReasonCode === "EXPLICIT_HUMAN_REQUEST");
  const mandatoryCancellation = status === "CANCELLED" && !explicitCancellation;
  return (
    <section className="panel safety-panel" aria-labelledby="safety-panel-title">
      <div className="panel-heading">
        <div>
          <h2 id="safety-panel-title">{copy.title}</h2>
          <p>{copy.subtitle}</p>
        </div>
        <span className={`status-pill safety-${state.safetyClassification.toLowerCase()}`}>
          {classificationLabel(state.safetyClassification, locale)}
        </span>
      </div>

      {refused ? <p role="alert">{copy.refused}</p> : null}
      {handoff ? (
        <div className="handoff-details" aria-live="polite">
          <p className="simulation-warning"><strong>{copy.simulation}</strong></p>
          <dl className="order-status-grid">
            <div><dt>{copy.reason}</dt><dd>{state.safetyReasonCode ?? copy.pending}</dd></div>
            <div><dt>{copy.queue}</dt><dd>{handoffStatusLabel(status, locale)}</dd></div>
            <div><dt>{copy.contact}</dt><dd>{copy.redacted}</dd></div>
            <div><dt>{copy.autoSubmit}</dt><dd>{copy.disabled}</dd></div>
          </dl>
          <FieldList title={copy.confirmed} values={state.confirmedFields} empty={copy.none} />
          <FieldList title={copy.unconfirmed} values={state.unconfirmedFields} empty={copy.none} />
          <FieldList title={copy.blocked} values={state.safetyBlockedActions} empty={copy.externalBlocked} />
          {failureCode ? <p role="status">{copy.failure}: {failureCode}; {copy.draftRetained}</p> : null}
          {explicitCancellation ? (
            <div role="status" aria-label="主动请求取消结果">
              <p>{copy.cancelled}</p>
              <p>{copy.draftRetained}</p>
              <p>{copy.reconfirm}</p>
            </div>
          ) : null}
          {mandatoryCancellation ? (
            <div role="status" aria-label="强制风险取消结果">
              <p>{copy.cancelledHold}</p>
              <p>{copy.noAutoSubmit}</p>
            </div>
          ) : null}
          {error ? <p role="alert">{error}</p> : null}
          {DEVELOPMENT_CONTROLS && state.handoffPublicId ? (
            <div className="simulation-controls" aria-label={copy.controls}>
              <button type="button" onClick={() => run(simulateAssign)} disabled={pending || status !== "PENDING"}>{copy.assign}</button>
              <button type="button" onClick={() => run(simulateConnect)} disabled={pending || status !== "SIMULATED_AGENT_ASSIGNED"}>{copy.connect}</button>
              <button type="button" onClick={() => run(simulateResolve)} disabled={pending || status !== "SIMULATED_AGENT_CONNECTED"}>{copy.resolve}</button>
              <button type="button" onClick={() => run(simulateFail)} disabled={pending || !isActive(status)}>{copy.fail}</button>
              <button type="button" onClick={() => run(cancelHandoff)} disabled={pending || !isActive(status)}>{copy.cancel}</button>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function FieldList({ title, values, empty }: { title: string; values: string[]; empty: string }) {
  return <p><strong>{title}：</strong>{values.length ? values.join("、") : empty}</p>;
}

function classificationLabel(value: string, locale: ConcreteLocale): string {
  const labels = {
    "zh-CN": { AUTO_DRAFT: "安全草稿", CONFIRM: "需要确认", HANDOFF: "需要模拟接管", REFUSE: "已拒绝" },
    "yue-Hant-HK": { AUTO_DRAFT: "安全草稿", CONFIRM: "需要確認", HANDOFF: "需要模擬接管", REFUSE: "已拒絕" },
    "en-HK": { AUTO_DRAFT: "Safe draft", CONFIRM: "Confirmation required", HANDOFF: "Simulated handoff required", REFUSE: "Refused" },
  }[locale] as Record<string, string>;
  return labels[value] ?? value;
}

function handoffStatusLabel(value: string, locale: ConcreteLocale): string {
  const zh = {
    REQUESTED: "已请求（模拟）",
    PENDING: "模拟排队中",
    SIMULATED_AGENT_ASSIGNED: "已分配模拟坐席",
    SIMULATED_AGENT_CONNECTED: "已连接模拟坐席（非真人）",
    RESOLVED: "模拟处理已完成",
    FAILED: "模拟接管失败",
    CANCELLED: "模拟接管已取消",
  } as Record<string, string>;
  const yue = { REQUESTED: "已請求（模擬）", PENDING: "模擬排隊中", SIMULATED_AGENT_ASSIGNED: "已分配模擬席位", SIMULATED_AGENT_CONNECTED: "已連接模擬席位（非真人）", RESOLVED: "模擬處理完成", FAILED: "模擬接管失敗", CANCELLED: "模擬接管已取消" } as Record<string, string>;
  const en = { REQUESTED: "Requested (simulation)", PENDING: "Queued in simulation", SIMULATED_AGENT_ASSIGNED: "Simulated seat assigned", SIMULATED_AGENT_CONNECTED: "Simulated seat connected (not a person)", RESOLVED: "Simulation resolved", FAILED: "Simulated handoff failed", CANCELLED: "Simulated handoff cancelled" } as Record<string, string>;
  return ({ "zh-CN": zh, "yue-Hant-HK": yue, "en-HK": en }[locale])[value] ?? value;
}

function isActive(value: string): boolean {
  return ["REQUESTED", "PENDING", "SIMULATED_AGENT_ASSIGNED", "SIMULATED_AGENT_CONNECTED"].includes(value);
}

const SAFETY_COPY: Record<ConcreteLocale, Record<string, string>> = {
  "zh-CN": { title: "安全决策", subtitle: "结构化政策结果；不会触发真实人工或外部下单", refused: "该目标已被拒绝，没有显示或执行成功结果。", simulation: "模拟人工接管，不是真实人工", reason: "转接原因", pending: "待记录", queue: "队列状态", contact: "联系方式", redacted: "默认脱敏：***", autoSubmit: "自动提交", disabled: "已禁用", confirmed: "已确认字段", unconfirmed: "未确认字段", blocked: "禁止动作", none: "无", externalBlocked: "外部提交与支付", failure: "失败代码", draftRetained: "订单草稿仍保留", cancelled: "模拟人工接管已取消", reconfirm: "需要重新确认后才能继续", cancelledHold: "模拟接管已取消，但安全限制仍然有效", noAutoSubmit: "订单不会自动提交", operationFailed: "模拟接管操作失败；订单仍保持冻结且未提交。请稍后重试。", controls: "模拟人工接管开发控制", assign: "模拟分配", connect: "模拟连接", resolve: "模拟解决", fail: "模拟失败", cancel: "取消模拟接管" },
  "yue-Hant-HK": { title: "安全決策", subtitle: "結構化政策結果；唔會觸發真人或者外部落單", refused: "呢個目標已被拒絕，冇顯示或者執行成功結果。", simulation: "模擬接管，唔係真人", reason: "接管原因", pending: "待記錄", queue: "隊列狀態", contact: "聯絡資料", redacted: "預設遮罩：***", autoSubmit: "自動提交", disabled: "已停用", confirmed: "已確認欄位", unconfirmed: "未確認欄位", blocked: "禁止動作", none: "冇", externalBlocked: "外部提交同付款", failure: "失敗代碼", draftRetained: "訂單草稿仍保留", cancelled: "模擬接管已取消", reconfirm: "要重新確認先可以繼續", cancelledHold: "模擬接管已取消，但安全限制仍然有效", noAutoSubmit: "訂單唔會自動提交", operationFailed: "模擬接管操作失敗；訂單仍然凍結而且未提交。請稍後再試。", controls: "模擬接管開發控制", assign: "模擬分配", connect: "模擬連接", resolve: "模擬解決", fail: "模擬失敗", cancel: "取消模擬接管" },
  "en-HK": { title: "Safety decision", subtitle: "Structured policy result; no real person or external order is triggered", refused: "This target was refused. No successful result was shown or performed.", simulation: "Simulated handoff — not a real person", reason: "Reason", pending: "Pending", queue: "Queue status", contact: "Contact", redacted: "Redacted by default: ***", autoSubmit: "Automatic submission", disabled: "Disabled", confirmed: "Confirmed fields", unconfirmed: "Unconfirmed fields", blocked: "Blocked actions", none: "None", externalBlocked: "External submission and payment", failure: "Failure code", draftRetained: "The order draft is retained", cancelled: "The simulated handoff is cancelled", reconfirm: "A new confirmation is required before continuing", cancelledHold: "The simulated handoff is cancelled, but safety restrictions remain", noAutoSubmit: "The order will not be submitted automatically", operationFailed: "The simulated handoff operation failed. The order remains frozen and unsubmitted.", controls: "Simulated handoff development controls", assign: "Simulate assignment", connect: "Simulate connection", resolve: "Simulate resolution", fail: "Simulate failure", cancel: "Cancel simulated handoff" },
};
