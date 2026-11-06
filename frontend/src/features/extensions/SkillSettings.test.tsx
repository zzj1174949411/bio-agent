import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SkillSettings } from "./SkillSettings";

it("shows Skill root, hash and changed-file re-enable state", () => {
  const onRescan = vi.fn();
  render(
    <SkillSettings
      root="C:/skills"
      skills={[
        {
          id: "skill-1",
          name: "RNA review",
          description: "Review counts",
          sha256: "a".repeat(64),
          enabled: false,
          changed: true,
        },
      ]}
      onRescan={onRescan}
      onSetEnabled={vi.fn()}
    />,
  );

  expect(screen.getByLabelText("Skill 根目录")).toHaveValue("C:/skills");
  expect(screen.getByText("文件已变化，需要重新启用")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "重新扫描 Skills" }));
  expect(onRescan).toHaveBeenCalledOnce();
});
