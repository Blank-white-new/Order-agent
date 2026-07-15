import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { MenuPanel } from "./MenuPanel";

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("MenuPanel", () => {
  test("renders grouped menu items and fills text through the callback", async () => {
    const onPickItem = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        okJson({
          categories: ["饭类"],
          items: [
            {
              id: "chicken_leg_rice",
              name: "鸡腿饭",
              category: "饭类",
              price: 26,
              tags: ["主食", "鸡肉"],
              options: ["不辣", "大份"],
              recommended_score: 9.1,
            },
          ],
        }),
      ),
    );

    render(<MenuPanel onPickItem={onPickItem} />);

    expect(await screen.findByText("饭类")).toBeInTheDocument();
    expect(screen.getByText("鸡腿饭")).toBeInTheDocument();
    expect(screen.getByText("26 HKD")).toBeInTheDocument();
    expect(screen.getByText("推荐")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "填入我要一份鸡腿饭" }));

    expect(onPickItem).toHaveBeenCalledWith("我要一份鸡腿饭");
  });

  test("does not crash when menu fields are missing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        okJson({
          items: [{ id: "partial", price: "unknown", tags: "bad", options: null }],
        }),
      ),
    );

    render(<MenuPanel onPickItem={vi.fn()} />);

    expect(await screen.findByText("未分类")).toBeInTheDocument();
    expect(screen.getByText("菜品名称待确认")).toBeInTheDocument();
    expect(screen.getByText("价格待确认")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "菜品名称待确认" })).toBeDisabled();
  });
});

function okJson(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  };
}
