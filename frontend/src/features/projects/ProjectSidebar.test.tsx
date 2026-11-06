import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProjectSidebar } from "./ProjectSidebar";

describe("ProjectSidebar", () => {
  it("creates, renames, and archives projects and conversations", () => {
    const onCreateProject = vi.fn(); const onRenameProject = vi.fn(); const onArchiveProject = vi.fn();
    const onCreateConversation = vi.fn(); const onRenameConversation = vi.fn(); const onArchiveConversation = vi.fn();
    render(<ProjectSidebar projects={[{id:"p1", title:"项目一", archived:false}]} conversations={[{id:"c1", project_id:"p1", title:"对话一", archived:false, selected_profile_id:null}]} onProject={vi.fn()} onConversation={vi.fn()} onCreateProject={onCreateProject} onRenameProject={onRenameProject} onArchiveProject={onArchiveProject} onCreateConversation={onCreateConversation} onRenameConversation={onRenameConversation} onArchiveConversation={onArchiveConversation} />);
    fireEvent.change(screen.getByLabelText("新项目名称"), {target:{value:"新项目"}}); fireEvent.click(screen.getByRole("button", {name:"创建项目"}));
    fireEvent.click(screen.getByRole("button", {name:"重命名项目一"})); fireEvent.click(screen.getByRole("button", {name:"归档项目一"}));
    fireEvent.change(screen.getByLabelText("新对话名称"), {target:{value:"新对话"}}); fireEvent.click(screen.getByRole("button", {name:"创建对话"}));
    fireEvent.click(screen.getByRole("button", {name:"重命名对话一"})); fireEvent.click(screen.getByRole("button", {name:"归档对话一"}));
    expect(onCreateProject).toHaveBeenCalledWith("新项目"); expect(onRenameProject).toHaveBeenCalledWith("p1", "项目一"); expect(onArchiveProject).toHaveBeenCalledWith("p1");
    expect(onCreateConversation).toHaveBeenCalledWith("p1", "新对话"); expect(onRenameConversation).toHaveBeenCalledWith("c1", "对话一"); expect(onArchiveConversation).toHaveBeenCalledWith("c1");
  });
});
