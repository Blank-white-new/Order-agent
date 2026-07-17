import { OrderStateView } from "../types/order";
import { ConcreteLocale } from "../i18n";

type NextStepHintProps = {
  state: OrderStateView;
  locale?: ConcreteLocale;
};

export function NextStepHint({ state, locale = "zh-CN" }: NextStepHintProps) {
  const title = locale === "en-HK" ? "Suggested next step" : locale === "yue-Hant-HK" ? "下一步建議" : "下一步建议";
  return (
    <section className="panel next-step" aria-labelledby="next-step-title">
      <h2 id="next-step-title">{title}</h2>
      <p>{nextStepText(state, locale)}</p>
    </section>
  );
}

export function nextStepText(state: OrderStateView, locale: ConcreteLocale = "zh-CN"): string {
  const copy = NEXT_STEP_COPY[locale];
  if (
    state.safetyClassification === "HANDOFF" &&
    !["RESOLVED", "CANCELLED"].includes(state.handoffStatus)
  ) {
    return copy.handoff;
  }
  if (state.safetyClassification === "REFUSE") {
    return copy.refused;
  }
  if (state.submitted) {
    return copy.submitted;
  }
  if (state.currentOrder.length === 0) {
    return copy.empty;
  }
  if (!state.fulfillmentType) {
    return copy.fulfillment;
  }
  if (state.stage === "collecting_address" || (state.fulfillmentType === "delivery" && !state.officialDeliveryAddress)) {
    return copy.address;
  }
  if (state.stage === "collecting_phone" || (state.fulfillmentType === "delivery" && !state.phone)) {
    return copy.phone;
  }
  return copy.continue;
}

const NEXT_STEP_COPY: Record<ConcreteLocale, Record<string, string>> = {
  "zh-CN": { handoff: "模拟人工接管处理中（不是真实人工）；自动提交已禁用，订单草稿会保留。", refused: "该目标未执行；可以继续处理自己的低风险模拟订单。", submitted: "订单已确认并保存到模拟系统，尚未发送给真实餐厅；可点击“新订单”继续。", empty: "你可以说：我要一份牛肉饭。", fulfillment: "请选择配送或自取。", address: "请补充配送地址。", phone: "请提供联系电话。", continue: "你可以继续添加菜品，或回复“确认订单”。" },
  "yue-Hant-HK": { handoff: "模擬接管處理中（唔係真人）；自動提交已停用，訂單草稿會保留。", refused: "呢個目標冇執行；你可以繼續處理自己嘅低風險模擬訂單。", submitted: "訂單已由客人確認並保存喺模擬系統，未送去真實餐廳。", empty: "你可以講：我要一份牛肉飯。", fulfillment: "請揀外賣或者自取。", address: "請補充合成外賣地址。", phone: "請提供合成聯絡電話。", continue: "你可以繼續加菜式，或者回覆「確認張單」。" },
  "en-HK": { handoff: "A simulated handoff is in progress (not a real person). Automatic submission is disabled and the draft is retained.", refused: "That target was not performed. You may continue managing your own low-risk simulated order.", submitted: "The customer-confirmed order is saved in the simulation and has not been sent to a real restaurant.", empty: "You can say: I want one portion of beef rice.", fulfillment: "Please choose delivery or pickup.", address: "Please provide a synthetic delivery address.", phone: "Please provide a synthetic contact number.", continue: "You may add more items or reply “confirm the order”." },
};
