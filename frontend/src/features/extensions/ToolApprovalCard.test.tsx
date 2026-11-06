import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ToolApprovalCard } from "./ToolApprovalCard";

it("shows the destination without approving on render and decides only after a click", () => {
  const decide = vi.fn();
  render(
    <ToolApprovalCard
      request={{
        id: "approval-1",
        tool: "mcp.fixture.echo",
        target: "http://127.0.0.1:8765/mcp",
        arguments: { text: "hello" },
        capabilityRevision: "r1",
        argumentsHash: "a".repeat(64),
        expiresAt: "2099-01-01T00:00:00Z",
      }}
      onDecide={decide}
    />,
  );

  expect(screen.getByText("http://127.0.0.1:8765/mcp")).toBeVisible();
  expect(decide).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "批准工具调用" }));
  expect(decide).toHaveBeenCalledWith("approval-1", "approve", "r1", "a".repeat(64));
});
