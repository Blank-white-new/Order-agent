import { useEffect, useState } from "react";
import { HandoffView, simulateAssign, simulateConnect, simulateFail, simulateResolve } from "../api/handoffApi";
import { OrderStateView } from "../types/order";

type Props = {
  sessionId: string;
  state: OrderStateView;
  onStatusChange?: (status: string) => void;
};

const DEVELOPMENT_CONTROLS = import.meta.env.DEV || import.meta.env.MODE === "test";

export function SafetyHandoffPanel({ sessionId, state, onStatusChange }: Props) {
  const [status, setStatus] = useState(state.handoffStatus);
  const [failureCode, setFailureCode] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setStatus(state.handoffStatus);
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
      onStatusChange?.(result.status);
    } catch {
      setError("模拟接管操作失败；订单仍保持冻结且未提交。请稍后重试。");
    } finally {
      setPending(false);
    }
  }

  const handoff = state.safetyClassification === "HANDOFF";
  const refused = state.safetyClassification === "REFUSE";
  return (
    <section className="panel safety-panel" aria-labelledby="safety-panel-title">
      <div className="panel-heading">
        <div>
          <h2 id="safety-panel-title">安全决策</h2>
          <p>结构化政策结果；不会触发真实人工或外部下单</p>
        </div>
        <span className={`status-pill safety-${state.safetyClassification.toLowerCase()}`}>
          {classificationLabel(state.safetyClassification)}
        </span>
      </div>

      {refused ? <p role="alert">该目标已被拒绝，没有显示或执行成功结果。</p> : null}
      {handoff ? (
        <div className="handoff-details" aria-live="polite">
          <p className="simulation-warning"><strong>模拟人工接管，不是真实人工</strong></p>
          <dl className="order-status-grid">
            <div><dt>转接原因</dt><dd>{state.safetyReasonCode ?? "待记录"}</dd></div>
            <div><dt>队列状态</dt><dd>{handoffStatusLabel(status)}</dd></div>
            <div><dt>联系方式</dt><dd>默认脱敏：***</dd></div>
            <div><dt>自动提交</dt><dd>已禁用</dd></div>
          </dl>
          <FieldList title="已确认字段" values={state.confirmedFields} empty="无" />
          <FieldList title="未确认字段" values={state.unconfirmedFields} empty="无" />
          <FieldList title="禁止动作" values={state.safetyBlockedActions} empty="外部提交与支付" />
          {failureCode ? <p role="status">失败代码：{failureCode}；草稿仍保留。</p> : null}
          {error ? <p role="alert">{error}</p> : null}
          {DEVELOPMENT_CONTROLS && state.handoffPublicId ? (
            <div className="simulation-controls" aria-label="模拟人工接管开发控制">
              <button type="button" onClick={() => run(simulateAssign)} disabled={pending || status !== "PENDING"}>模拟分配</button>
              <button type="button" onClick={() => run(simulateConnect)} disabled={pending || status !== "SIMULATED_AGENT_ASSIGNED"}>模拟连接</button>
              <button type="button" onClick={() => run(simulateResolve)} disabled={pending || status !== "SIMULATED_AGENT_CONNECTED"}>模拟解决</button>
              <button type="button" onClick={() => run(simulateFail)} disabled={pending || !isActive(status)}>模拟失败</button>
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

function classificationLabel(value: string): string {
  return ({ AUTO_DRAFT: "安全草稿", CONFIRM: "需要确认", HANDOFF: "需要模拟接管", REFUSE: "已拒绝" } as Record<string, string>)[value] ?? value;
}

function handoffStatusLabel(value: string): string {
  return ({
    REQUESTED: "已请求（模拟）",
    PENDING: "模拟排队中",
    SIMULATED_AGENT_ASSIGNED: "已分配模拟坐席",
    SIMULATED_AGENT_CONNECTED: "已连接模拟坐席（非真人）",
    RESOLVED: "模拟处理已完成",
    FAILED: "模拟接管失败",
    CANCELLED: "模拟接管已取消",
  } as Record<string, string>)[value] ?? value;
}

function isActive(value: string): boolean {
  return ["REQUESTED", "PENDING", "SIMULATED_AGENT_ASSIGNED", "SIMULATED_AGENT_CONNECTED"].includes(value);
}
