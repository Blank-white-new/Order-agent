import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { MessageBubble } from "./MessageBubble";

describe("MessageBubble", () => {
  test("keeps technical trace behind a collapsed debug disclosure", () => {
    render(
      <MessageBubble
        role="agent"
        text="已加入一份牛肉饭"
        trace={{
          finalIntent: "order_food",
          userMessage: "送到示例大学一号楼，电话 13800000000",
          officialAddressAfter: "示例大学一号楼",
          note: "联系电话 13800000000",
        }}
      />,
    );

    const summary = screen.getByText("调试信息（默认折叠）");
    const details = summary.closest("details");
    expect(details).not.toHaveAttribute("open");
    expect(details).toHaveTextContent("order_food");
    expect(details).toHaveTextContent("138****0000");
    expect(details).not.toHaveTextContent("13800000000");
    expect(details).not.toHaveTextContent("示例大学一号楼");
  });
});
