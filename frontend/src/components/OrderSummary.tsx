import {
  formatPrice,
  hasUnknownOrderPrice,
  knownOrderTotal,
  orderLineSubtotal,
  OrderStateView,
} from "../types/order";

type OrderSummaryProps = {
  state: OrderStateView;
};

export function OrderSummary({ state }: OrderSummaryProps) {
  const hasItems = state.currentOrder.length > 0;
  const total = knownOrderTotal(state.currentOrder);
  const hasUnknownPrice = hasUnknownOrderPrice(state.currentOrder);

  return (
    <section className="panel order-summary" aria-labelledby="order-summary-title">
      <div className="panel-heading">
        <div>
          <h2 id="order-summary-title">当前订单状态</h2>
          <p>基于当前会话最近返回的状态显示</p>
        </div>
        {state.safetyClassification === "HANDOFF" && !["RESOLVED", "CANCELLED"].includes(state.handoffStatus) ? (
          <span className="status-pill warning">自动提交已冻结</span>
        ) : state.lifecycleStatus === "CUSTOMER_CONFIRMED" ? (
          <span className="status-pill success">顾客已确认</span>
        ) : (
          <span className="status-pill">进行中</span>
        )}
      </div>

      {hasItems ? (
        <ul className="order-lines" aria-label="已点菜品">
          {state.currentOrder.map((item, index) => {
            const subtotal = orderLineSubtotal(item);
            const note = visibleNote(item);
            return (
              <li key={`${item.key}-${index}`} className="order-line">
                <div className="order-line-main">
                  <strong>{item.name}</strong>
                  <span>
                    {item.category ?? "分类待确认"} · {item.quantity}
                    {item.unit ?? "份"}
                  </span>
                  {item.options.length > 0 ? <small>口味：{item.options.join("、")}</small> : null}
                  {item.spicyLevel ? <small>辣度：{item.spicyLevel}</small> : null}
                  {item.exclusions.length > 0 ? <small>忌口：{item.exclusions.map((value) => `不要${value}`).join("、")}</small> : null}
                  {note ? <small>备注：{note}</small> : null}
                </div>
                <div className="order-line-price">
                  <span>单价：{formatPrice(item.priceMinor, item.currency)}</span>
                  <span>小计：{subtotal === null ? "价格待确认" : formatPrice(subtotal, item.currency)}</span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="empty-state">还没有添加菜品。</p>
      )}

      <dl className="order-status-grid">
        <div>
          <dt>取餐方式</dt>
          <dd>{fulfillmentLabel(state.fulfillmentType)}</dd>
        </div>
        <div>
          <dt>配送地址</dt>
          <dd>{addressLabel(state)}</dd>
        </div>
        <div>
          <dt>联系电话</dt>
          <dd>{phoneLabel(state)}</dd>
        </div>
        <div>
          <dt>当前阶段</dt>
          <dd>{stageLabel(state.stage)}</dd>
        </div>
        <div>
          <dt>商家状态</dt>
          <dd>{state.merchantStatus === "NOT_INTEGRATED" ? "未接入真实餐厅" : state.merchantStatus}</dd>
        </div>
      </dl>

      {hasItems ? (
        <div className="order-total" aria-label="订单总价">
          <span>总价</span>
          <strong>{totalLabel(total, hasUnknownPrice, state.currentOrder[0]?.currency ?? "HKD")}</strong>
        </div>
      ) : null}

      {state.submittedOrderId ? (
        <p className="order-id">本地模拟订单号：{state.submittedOrderId}</p>
      ) : null}
    </section>
  );
}

function fulfillmentLabel(value: string | null): string {
  if (value === "delivery") {
    return "配送";
  }
  if (value === "pickup") {
    return "自取";
  }
  return value ?? "待确认";
}

function addressLabel(state: OrderStateView): string {
  if (state.fulfillmentType === "pickup") {
    return "自取无需填写";
  }
  if (state.officialDeliveryAddress) {
    return `已填写：${state.officialDeliveryAddress}`;
  }
  if (state.pendingDeliveryAddress) {
    return `待确认：${state.pendingDeliveryAddress}`;
  }
  return "待填写";
}

function phoneLabel(state: OrderStateView): string {
  if (state.phone) {
    return `已填写：${maskPhone(state.phone)}`;
  }
  if (state.fulfillmentType === "pickup") {
    return "自取可不填写";
  }
  return "待填写";
}

function visibleNote(item: { exclusions: string[]; notes: string | null }): string | null {
  if (!item.notes) {
    return null;
  }
  const duplicateNotes = new Set(item.exclusions.map((value) => `不要${value}`));
  const visibleParts = item.notes
    .split("；")
    .map((part) => part.trim())
    .filter((part) => part && !duplicateNotes.has(part));
  return visibleParts.length > 0 ? visibleParts.join("；") : null;
}

function maskPhone(phone: string): string {
  const compact = phone.replace(/[\s-]/g, "");
  if (/^1[3-9]\d{9}$/.test(compact)) {
    return `${compact.slice(0, 3)}****${compact.slice(-4)}`;
  }
  if (compact.length > 4) {
    return `${"*".repeat(Math.min(4, compact.length - 4))}${compact.slice(-4)}`;
  }
  return "****";
}

function stageLabel(value: string | null): string {
  if (value === "ordering") {
    return "点餐中";
  }
  if (value === "collecting_address") {
    return "等待地址";
  }
  if (value === "collecting_phone") {
    return "等待电话";
  }
  if (value === "confirming") {
    return "待确认";
  }
  if (value === "submitted") {
    return "顾客已确认（尚未发送）";
  }
  return value ?? "待确认";
}

function totalLabel(total: number, hasUnknownPrice: boolean, currency: string): string {
  if (!hasUnknownPrice) {
    return formatPrice(total, currency);
  }
  if (total > 0) {
    return `已知 ${formatPrice(total, currency)}，部分价格待确认`;
  }
  return "价格待确认";
}
