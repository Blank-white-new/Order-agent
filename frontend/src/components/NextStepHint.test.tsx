import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { normalizeOrderState } from "../types/order";
import { NextStepHint } from "./NextStepHint";

describe("NextStepHint", () => {
  test("prompts ordering when the order is empty", () => {
    render(<NextStepHint state={normalizeOrderState({ current_order: [] })} />);

    expect(screen.getByText("你可以说：我要一份牛肉饭。")).toBeInTheDocument();
  });

  test("prompts confirmation when items and required delivery fields are present", () => {
    render(
      <NextStepHint
        state={normalizeOrderState({
          current_order: [{ name: "鸡腿饭", price: 26, quantity: 1 }],
          fulfillment_type: "delivery",
          official_delivery_address: "中山大学南校园",
          phone: "13812345678",
        })}
      />,
    );

    expect(screen.getByText("你可以继续添加菜品，或回复“确认订单”。")).toBeInTheDocument();
  });

  test("prompts for address when delivery address is missing", () => {
    render(
      <NextStepHint
        state={normalizeOrderState({
          current_order: [{ name: "鸡腿饭", price: 26, quantity: 1 }],
          fulfillment_type: "delivery",
          stage: "collecting_address",
        })}
      />,
    );

    expect(screen.getByText("请补充配送地址。")).toBeInTheDocument();
  });

  test("prompts for phone when delivery phone is missing", () => {
    render(
      <NextStepHint
        state={normalizeOrderState({
          current_order: [{ name: "鸡腿饭", price: 26, quantity: 1 }],
          fulfillment_type: "delivery",
          official_delivery_address: "中山大学南校园",
          stage: "collecting_phone",
        })}
      />,
    );

    expect(screen.getByText("请提供联系电话。")).toBeInTheDocument();
  });

  test("makes submitted demo orders explicit", () => {
    render(<NextStepHint state={normalizeOrderState({ submitted: true })} />);

    expect(screen.getByText(/订单已确认并保存到模拟系统/)).toBeInTheDocument();
    expect(screen.getByText(/尚未发送给真实餐厅/)).toBeInTheDocument();
    expect(screen.getByText(/点击“新订单”继续/)).toBeInTheDocument();
  });
});
