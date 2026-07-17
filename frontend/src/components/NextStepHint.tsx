import { OrderStateView } from "../types/order";

type NextStepHintProps = {
  state: OrderStateView;
};

export function NextStepHint({ state }: NextStepHintProps) {
  return (
    <section className="panel next-step" aria-labelledby="next-step-title">
      <h2 id="next-step-title">下一步建议</h2>
      <p>{nextStepText(state)}</p>
    </section>
  );
}

export function nextStepText(state: OrderStateView): string {
  if (
    state.safetyClassification === "HANDOFF" &&
    !["RESOLVED", "CANCELLED"].includes(state.handoffStatus)
  ) {
    return "模拟人工接管处理中（不是真实人工）；自动提交已禁用，订单草稿会保留。";
  }
  if (state.safetyClassification === "REFUSE") {
    return "该目标未执行；可以继续处理自己的低风险模拟订单。";
  }
  if (state.submitted) {
    return "订单已确认并保存到模拟系统，尚未发送给真实餐厅；可点击“新订单”继续。";
  }
  if (state.currentOrder.length === 0) {
    return "你可以说：我要一份牛肉饭。";
  }
  if (!state.fulfillmentType) {
    return "请选择配送或自取。";
  }
  if (state.stage === "collecting_address" || (state.fulfillmentType === "delivery" && !state.officialDeliveryAddress)) {
    return "请补充配送地址。";
  }
  if (state.stage === "collecting_phone" || (state.fulfillmentType === "delivery" && !state.phone)) {
    return "请提供联系电话。";
  }
  return "你可以继续添加菜品，或回复“确认订单”。";
}
