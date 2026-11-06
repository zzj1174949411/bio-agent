import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResourcePanel } from "./ResourcePanel";

describe("ResourcePanel", () => {
  it("renders QC, plots, a sandbox report, and individually downloadable artifacts", () => {
    render(<ResourcePanel run={{status:"COMPLETED", qcStatus:"PASS", reportUrl:"/report.html", plots:[{name:"MA plot", url:"/ma.png"}], artifacts:[{name:"manifest.json", url:"/manifest"}]}} />);
    expect(screen.getByText("QC: PASS")).toBeInTheDocument(); expect(screen.getByAltText("MA plot")).toHaveAttribute("src", "/ma.png"); expect(screen.getByTitle("报告预览")).toHaveAttribute("sandbox", ""); expect(screen.getByRole("link", {name:"下载 manifest.json"})).toHaveAttribute("href", "/manifest");
  });
});
