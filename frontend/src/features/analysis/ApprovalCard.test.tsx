import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCard } from "./ApprovalCard";

describe("ApprovalCard", () => { it("requires confirmation and the displayed revision for approval", () => { const onApprove=vi.fn(); render(<ApprovalCard revision={2} onApprove={onApprove}/>); expect(screen.getByText(/revision 2/i)).toBeInTheDocument(); const button = screen.getByRole("button",{name:"批准分析"}); expect(button).toBeDisabled(); fireEvent.click(screen.getByLabelText("我已核对本次方案")); fireEvent.click(button); expect(onApprove).toHaveBeenCalledWith(2); }); });
