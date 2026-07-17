import {
  formatPrice,
  hasUnknownOrderPrice,
  knownOrderTotal,
  orderLineSubtotal,
  OrderStateView,
} from "../types/order";
import { ConcreteLocale } from "../i18n";

type OrderSummaryProps = {
  state: OrderStateView;
  locale?: ConcreteLocale;
};

export function OrderSummary({ state, locale = "zh-CN" }: OrderSummaryProps) {
  const copy = ORDER_COPY[locale];
  const hasItems = state.currentOrder.length > 0;
  const total = knownOrderTotal(state.currentOrder);
  const hasUnknownPrice = hasUnknownOrderPrice(state.currentOrder);

  return (
    <section className="panel order-summary" aria-labelledby="order-summary-title">
      <div className="panel-heading">
        <div>
          <h2 id="order-summary-title">{copy.title}</h2>
          <p>{copy.subtitle}</p>
        </div>
        {state.safetyClassification === "HANDOFF" && !["RESOLVED", "CANCELLED"].includes(state.handoffStatus) ? (
          <span className="status-pill warning">{copy.frozen}</span>
        ) : state.lifecycleStatus === "CUSTOMER_CONFIRMED" ? (
          <span className="status-pill success">{copy.confirmed}</span>
        ) : (
          <span className="status-pill">{copy.inProgress}</span>
        )}
      </div>

      {hasItems ? (
        <ul className="order-lines" aria-label={copy.items}>
          {state.currentOrder.map((item, index) => {
            const subtotal = orderLineSubtotal(item);
            const note = visibleNote(item);
            return (
              <li key={`${item.key}-${index}`} className="order-line">
                <div className="order-line-main">
                  <strong>{item.name}</strong>
                  <span>
                    {item.category ?? copy.categoryPending} · {item.quantity}
                    {item.unit ?? copy.unit}
                  </span>
                  {item.options.length > 0 ? <small>{copy.options}{copy.separator}{item.options.join(locale === "en-HK" ? ", " : "、")}</small> : null}
                  {item.spicyLevel ? <small>{copy.spicy}{copy.separator}{item.spicyLevel}</small> : null}
                  {item.exclusions.length > 0 ? <small>{copy.exclusions}{copy.separator}{formatExclusions(item.exclusions, locale)}</small> : null}
                  {note ? <small>{copy.note}{copy.separator}{note}</small> : null}
                </div>
                <div className="order-line-price">
                  <span>{copy.unitPrice}{copy.separator}{formatPrice(item.priceMinor, item.currency)}</span>
                  <span>{copy.subtotal}{copy.separator}{subtotal === null ? copy.pricePending : formatPrice(subtotal, item.currency)}</span>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="empty-state">{copy.empty}</p>
      )}

      <dl className="order-status-grid">
        <div>
          <dt>{copy.fulfillment}</dt>
          <dd>{fulfillmentLabel(state.fulfillmentType, locale)}</dd>
        </div>
        <div>
          <dt>{copy.address}</dt>
          <dd>{addressLabel(state, locale)}</dd>
        </div>
        <div>
          <dt>{copy.phone}</dt>
          <dd>{phoneLabel(state, locale)}</dd>
        </div>
        <div>
          <dt>{copy.stage}</dt>
          <dd>{stageLabel(state.stage, locale)}</dd>
        </div>
        <div>
          <dt>{copy.merchant}</dt>
          <dd>{state.merchantStatus === "NOT_INTEGRATED" ? copy.notIntegrated : state.merchantStatus}</dd>
        </div>
      </dl>

      {hasItems ? (
        <div className="order-total" aria-label={copy.total}>
          <span>{copy.total}</span>
          <strong>{totalLabel(total, hasUnknownPrice, state.currentOrder[0]?.currency ?? "HKD", locale)}</strong>
        </div>
      ) : null}

      {state.submittedOrderId ? (
        <p className="order-id">{copy.orderId}{copy.separator}{state.submittedOrderId}</p>
      ) : null}
    </section>
  );
}

function fulfillmentLabel(value: string | null, locale: ConcreteLocale): string {
  const copy = ORDER_COPY[locale];
  if (value === "delivery") {
    return copy.delivery;
  }
  if (value === "pickup") {
    return copy.pickup;
  }
  return value ?? copy.pending;
}

function addressLabel(state: OrderStateView, locale: ConcreteLocale): string {
  const copy = ORDER_COPY[locale];
  if (state.fulfillmentType === "pickup") {
    return copy.pickupNoAddress;
  }
  if (state.officialDeliveryAddress) {
    return `${copy.recorded}${copy.separator}${state.officialDeliveryAddress}`;
  }
  if (state.pendingDeliveryAddress) {
    return `${copy.pending}${copy.separator}${state.pendingDeliveryAddress}`;
  }
  return copy.toFill;
}

function phoneLabel(state: OrderStateView, locale: ConcreteLocale): string {
  const copy = ORDER_COPY[locale];
  if (state.phone) {
    return `${copy.recorded}${copy.separator}${maskPhone(state.phone)}`;
  }
  if (state.fulfillmentType === "pickup") {
    return copy.pickupPhoneOptional;
  }
  return copy.toFill;
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

function stageLabel(value: string | null, locale: ConcreteLocale): string {
  const copy = ORDER_COPY[locale];
  if (value === "ordering") {
    return copy.ordering;
  }
  if (value === "collecting_address") {
    return copy.waitAddress;
  }
  if (value === "collecting_phone") {
    return copy.waitPhone;
  }
  if (value === "confirming") {
    return copy.pending;
  }
  if (value === "submitted") {
    return copy.confirmedNotSent;
  }
  return value ?? copy.pending;
}

function formatExclusions(values: string[], locale: ConcreteLocale): string {
  if (locale === "zh-CN") return values.map((value) => `不要${value}`).join("、");
  if (locale === "yue-Hant-HK") return values.map((value) => `走${value}`).join("、");
  return values.map((value) => `without ${value}`).join(", ");
}

function totalLabel(total: number, hasUnknownPrice: boolean, currency: string, locale: ConcreteLocale): string {
  const copy = ORDER_COPY[locale];
  if (!hasUnknownPrice) {
    return formatPrice(total, currency);
  }
  if (total > 0) {
    return `${copy.known} ${formatPrice(total, currency)}; ${copy.somePending}`;
  }
  return copy.pricePending;
}

const ORDER_COPY: Record<ConcreteLocale, Record<string, string>> = {
  "zh-CN": { title: "当前订单状态", subtitle: "基于当前会话最近返回的状态显示", separator: "：", frozen: "自动提交已冻结", confirmed: "顾客已确认", inProgress: "进行中", items: "已点菜品", categoryPending: "分类待确认", unit: "份", options: "口味", spicy: "辣度", exclusions: "忌口", note: "备注", unitPrice: "单价", subtotal: "小计", pricePending: "价格待确认", empty: "还没有添加菜品。", fulfillment: "取餐方式", address: "配送地址", phone: "联系电话", stage: "当前阶段", merchant: "商家状态", notIntegrated: "未接入真实餐厅", total: "订单总价", orderId: "本地模拟订单号", delivery: "配送", pickup: "自取", pending: "待确认", pickupNoAddress: "自取无需填写", recorded: "已填写", toFill: "待填写", pickupPhoneOptional: "自取可不填写", ordering: "点餐中", waitAddress: "等待地址", waitPhone: "等待电话", confirmedNotSent: "顾客已确认（尚未发送）", known: "已知", somePending: "部分价格待确认" },
  "yue-Hant-HK": { title: "目前訂單狀態", subtitle: "按目前對話最近回傳嘅權威狀態顯示", separator: "：", frozen: "自動提交已凍結", confirmed: "客人已確認", inProgress: "處理中", items: "已叫菜式", categoryPending: "分類待確認", unit: "份", options: "口味", spicy: "辣度", exclusions: "走料", note: "備註", unitPrice: "單價", subtotal: "小計", pricePending: "價錢待確認", empty: "仲未加菜式。", fulfillment: "取餐方式", address: "外賣地址", phone: "聯絡電話", stage: "目前階段", merchant: "商戶狀態", notIntegrated: "未接入真實餐廳", total: "訂單總價", orderId: "本地模擬訂單號", delivery: "外賣", pickup: "自取", pending: "待確認", pickupNoAddress: "自取唔使填地址", recorded: "已填寫", toFill: "待填寫", pickupPhoneOptional: "自取可以唔填", ordering: "落單中", waitAddress: "等候地址", waitPhone: "等候電話", confirmedNotSent: "客人已確認（尚未傳送）", known: "已知", somePending: "部分價錢待確認" },
  "en-HK": { title: "Current order status", subtitle: "Authoritative state from the latest response in this session", separator: ": ", frozen: "Automatic submission frozen", confirmed: "Customer confirmed", inProgress: "In progress", items: "Ordered items", categoryPending: "Category pending", unit: "portion(s)", options: "Options", spicy: "Spice level", exclusions: "Exclusions", note: "Note", unitPrice: "Unit price", subtotal: "Subtotal", pricePending: "Price pending confirmation", empty: "No items have been added.", fulfillment: "Fulfilment", address: "Delivery address", phone: "Contact number", stage: "Current stage", merchant: "Merchant status", notIntegrated: "No real restaurant connected", total: "Order total", orderId: "Local simulated order ID", delivery: "Delivery", pickup: "Pickup", pending: "Pending confirmation", pickupNoAddress: "No address is required for pickup", recorded: "Recorded", toFill: "Not provided", pickupPhoneOptional: "Optional for pickup", ordering: "Ordering", waitAddress: "Waiting for address", waitPhone: "Waiting for contact number", confirmedNotSent: "Customer confirmed (not sent)", known: "Known", somePending: "some prices are pending confirmation" },
};
