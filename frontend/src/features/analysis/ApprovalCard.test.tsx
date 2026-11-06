import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalCard } from "./ApprovalCard";

describe("ApprovalCard", () => { it("requires the displayed revision for approval", () => { const onApprove=vi.fn(); render(<ApprovalCard revision={2} onApprove={onApprove}/>); expect(screen.getByText(/revision 2/i)).toBeInTheDocument(); screen.getByRole("button",{name:"批准分析"}).click(); expect(onApprove).toHaveBeenCalledWith(2); }); });
