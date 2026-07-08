import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { normalizeOrderState } from "../types/order";
import { OrderSummary } from "./OrderSummary";

describe("OrderSummary", () => {
  test("shows a friendly empty state", () => {
    render(<OrderSummary state={normalizeOrderState({ current_order: [] })} />);

    expect(screen.getByText("当前订单状态")).toBeInTheDocument();
    expect(screen.getByText("基于当前会话最近返回的状态显示")).toBeInTheDocument();
    expect(screen.getByText("还没有添加菜品。")).toBeInTheDocument();
  });

  test("shows item quantity, unit price, subtotal, total, and delivery slots", () => {
    render(
      <OrderSummary
        state={normalizeOrderState({
          current_order: [
            {
              item_id: "chicken_leg_rice",
              name: "鸡腿饭",
              price: 26,
              quantity: 2,
              options: ["不辣"],
              notes: "少油",
              category: "饭类",
              unit: "份",
            },
          ],
          fulfillment_type: "delivery",
          official_delivery_address: "中山大学南校园",
          phone: "13812345678",
          stage: "confirming",
        })}
      />,
    );

    expect(screen.getByText("鸡腿饭")).toBeInTheDocument();
    expect(screen.getByText("饭类 · 2份")).toBeInTheDocument();
    expect(screen.getByText("口味：不辣")).toBeInTheDocument();
    expect(screen.getByText("备注：少油")).toBeInTheDocument();
    expect(screen.getByText("单价：26 元")).toBeInTheDocument();
    expect(screen.getByText("小计：52 元")).toBeInTheDocument();
    expect(screen.getByText("52 元")).toBeInTheDocument();
    expect(screen.getByText("配送")).toBeInTheDocument();
    expect(screen.getByText("已填写：中山大学南校园")).toBeInTheDocument();
    expect(screen.getByText("已填写：13812345678")).toBeInTheDocument();
  });

  test("does not crash when item price is missing or invalid", () => {
    render(
      <OrderSummary
        state={normalizeOrderState({
          current_order: [
            { name: "牛肉饭", price: "28", quantity: 2, category: "饭类" },
            { name: "可乐", quantity: 1, category: "饮品" },
          ],
          fulfillment_type: "delivery",
        })}
      />,
    );

    expect(screen.getByText("牛肉饭")).toBeInTheDocument();
    expect(screen.getByText("可乐")).toBeInTheDocument();
    expect(screen.getAllByText(/价格待确认/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("待填写").length).toBeGreaterThan(0);
  });

  test("does not crash when current_order entries are incomplete", () => {
    render(
      <OrderSummary
        state={normalizeOrderState({
          current_order: [null, { price: 8, quantity: "two" }],
          fulfillment_type: "pickup",
        })}
      />,
    );

    expect(screen.getAllByText("菜品待确认").length).toBeGreaterThan(0);
    expect(screen.getByText("自取")).toBeInTheDocument();
    expect(screen.getByText("自取无需填写")).toBeInTheDocument();
  });
});
