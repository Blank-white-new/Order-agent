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
    render(
      <SafetyHandoffPanel
        sessionId="safety-ui-test"
        state={normalizeOrderState({ safety_classification: classification })}
      />,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
    if (classification === "REFUSE") {
      expect(screen.getByRole("alert")).toHaveTextContent("没有显示或执行成功结果");
    }
  });

  test("labels connected status as simulated and never as a real human", () => {
    render(
      <SafetyHandoffPanel
        sessionId="safety-ui-test"
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
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) => Promise.resolve(okJson({
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
        sessionId="safety-ui-test"
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
    expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toMatchObject({
      sessionId: "safety-ui-test",
    });
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
        sessionId="safety-ui-test"
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

  test("explicit-request cancellation preserves draft and requires reconfirmation in text", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(okJson({
      handoffId: "SIM-HO-EXPLICIT",
      status: "CANCELLED",
      reasonCode: "EXPLICIT_HUMAN_REQUEST",
      failureCode: "CASE_CANCELLED",
      mayContinueDraft: true,
      requiresNewConfirmation: true,
      safetyHoldActive: false,
    }))));
    render(
      <SafetyHandoffPanel
        sessionId="explicit-cancel-ui"
        state={normalizeOrderState({
          safety_classification: "HANDOFF",
          safety_reason_code: "EXPLICIT_HUMAN_REQUEST",
          handoff_public_id: "SIM-HO-EXPLICIT",
          handoff_status: "PENDING",
        })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "取消模拟接管" }));

    expect(await screen.findByText("模拟人工接管已取消")).toBeInTheDocument();
    expect(screen.getByText("订单草稿仍保留")).toBeInTheDocument();
    expect(screen.getByText("需要重新确认后才能继续")).toBeInTheDocument();
    expect(screen.queryByText("订单已成功")).not.toBeInTheDocument();
    expect(screen.queryByText("餐厅已接受")).not.toBeInTheDocument();
    expect(screen.queryByText("真人已连接")).not.toBeInTheDocument();
    expect(screen.queryByText("可以直接提交")).not.toBeInTheDocument();
  });

  test("mandatory-risk cancellation keeps a visible safety block", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(okJson({
      handoffId: "SIM-HO-MANDATORY",
      status: "CANCELLED",
      reasonCode: "SEVERE_ALLERGY",
      failureCode: "CASE_CANCELLED",
      mayContinueDraft: false,
      requiresNewConfirmation: true,
      safetyHoldActive: true,
    }))));
    render(
      <SafetyHandoffPanel
        sessionId="mandatory-cancel-ui"
        state={normalizeOrderState({
          safety_classification: "HANDOFF",
          safety_reason_code: "SEVERE_ALLERGY",
          handoff_public_id: "SIM-HO-MANDATORY",
          handoff_status: "PENDING",
        })}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "取消模拟接管" }));

    expect(await screen.findByText("模拟接管已取消，但安全限制仍然有效")).toBeInTheDocument();
    expect(screen.getByText("订单不会自动提交")).toBeInTheDocument();
    expect(screen.queryByText("可以直接提交")).not.toBeInTheDocument();
  });
});

function okJson(body: unknown) {
  return { ok: true, json: async () => body };
}
