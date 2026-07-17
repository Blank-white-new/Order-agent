import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { normalizeOrderState } from "../types/order";
import { SafetyHandoffPanel } from "./SafetyHandoffPanel";


beforeEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SafetyHandoffPanel", () => {
  test.each([
    ["AUTO_DRAFT", "安全草稿"],
    ["CONFIRM", "需要确认"],
    ["REFUSE", "已拒绝"],
  ])("renders %s as text rather than relying on color", (classification, label) => {
    render(<SafetyHandoffPanel state={normalizeOrderState({ safety_classification: classification })} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    if (classification === "REFUSE") {
      expect(screen.getByRole("alert")).toHaveTextContent("没有显示或执行成功结果");
    }
  });

  test("labels connected status as simulated and never as a real human", () => {
    render(
      <SafetyHandoffPanel
        state={normalizeOrderState({
          safety_classification: "HANDOFF",
          safety_reason_code: "SEVERE_ALLERGY",
          handoff_public_id: "SIM-HO-TEST",
          handoff_status: "SIMULATED_AGENT_CONNECTED",
          confirmed_fields: ["final_order"],
          unconfirmed_fields: ["allergy_details"],
          safety_blocked_actions: ["SUBMIT_TO_MERCHANT"],
        })}
      />,
    );
    expect(screen.getByText("模拟人工接管，不是真实人工")).toBeInTheDocument();
    expect(screen.getByText("已连接模拟坐席（非真人）")).toBeInTheDocument();
    expect(screen.getByText(/默认脱敏/)).toBeInTheDocument();
    expect(screen.queryByText(/^真人已连接$/)).not.toBeInTheDocument();
  });

  test("development control follows the allowed simulated state sequence", async () => {
    const fetchMock = vi.fn((_url: string) => Promise.resolve(okJson({
      handoffId: "SIM-HO-TEST",
      status: "SIMULATED_AGENT_ASSIGNED",
      reasonCode: "SEVERE_ALLERGY",
      failureCode: null,
      simulationNotice: "模拟人工接管，不是真实人工",
    })));
    vi.stubGlobal("fetch", fetchMock);
    const onStatusChange = vi.fn();
    render(
      <SafetyHandoffPanel
        state={normalizeOrderState({
          safety_classification: "HANDOFF",
          safety_reason_code: "SEVERE_ALLERGY",
          handoff_public_id: "SIM-HO-TEST",
          handoff_status: "PENDING",
        })}
        onStatusChange={onStatusChange}
      />,
    );
    expect(screen.getByRole("button", { name: "模拟连接" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "模拟分配" }));
    await waitFor(() => expect(onStatusChange).toHaveBeenCalledWith("SIMULATED_AGENT_ASSIGNED"));
    expect(fetchMock.mock.calls[0][0]).toContain("/simulate-assign");
  });

  test("failure response keeps explicit draft-preservation wording", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(okJson({
      handoffId: "SIM-HO-TEST",
      status: "FAILED",
      reasonCode: "SYSTEM_FAILURE",
      failureCode: "NO_AGENT_AVAILABLE",
    }))));
    render(
      <SafetyHandoffPanel
        state={normalizeOrderState({
          safety_classification: "HANDOFF",
          handoff_public_id: "SIM-HO-TEST",
          handoff_status: "PENDING",
        })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "模拟失败" }));
    expect(await screen.findByText(/NO_AGENT_AVAILABLE/)).toHaveTextContent("草稿仍保留");
  });
});

function okJson(body: unknown) {
  return { ok: true, json: async () => body };
}
