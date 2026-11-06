import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ClarificationCard } from "./ClarificationCard";

describe("ClarificationCard", () => {
  it("shows input.required and sends its revision, while rejecting blank values", () => {
    const onRespond = vi.fn(); render(<ClarificationCard requestId="r1" revision={3} question="请选择对照组" onRespond={onRespond} />);
    expect(screen.getByText("请选择对照组")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", {name:"提交澄清"})); expect(onRespond).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox", {name:"澄清回答"}), {target:{value:"Control"}}); fireEvent.click(screen.getByRole("button", {name:"提交澄清"})); expect(onRespond).toHaveBeenCalledWith("r1", 3, "Control");
  });
});
