import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SafeMarkdown } from "./SafeMarkdown";

describe("SafeMarkdown", () => {
  it("does not execute raw HTML and only links http(s) URLs", () => {
    render(<SafeMarkdown source={'<img src="x" onerror="alert(1)"> [安全](https://example.com) [危险](javascript:alert(1))'} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument(); expect(screen.getByRole("link", {name:"安全"})).toHaveAttribute("href", "https://example.com"); expect(screen.queryByRole("link", {name:"危险"})).not.toBeInTheDocument();
  });
});
