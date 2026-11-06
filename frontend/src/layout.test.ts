import { describe, expect, it } from "vitest";
import { WORKBENCH_LAYOUT } from "./layout";

describe("responsive workbench layout", () => {
  it("defines the 1200 and 900 pixel handoff points used by the CSS layout", () => {
    expect(WORKBENCH_LAYOUT.wideColumnsMinWidth).toBe(1200); expect(WORKBENCH_LAYOUT.compactColumnsMinWidth).toBe(900);
  });
});
