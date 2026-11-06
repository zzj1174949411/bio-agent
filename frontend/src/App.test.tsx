import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { App } from "./App";
import { ApiClient } from "./api/client";

test("a late conversation creation cannot navigate away from the user's new project", async () => {
  localStorage.clear(); const api = new ApiClient(); const projects = [{ id: "a", title: "项目A", archived: false }, { id: "b", title: "项目B", archived: false }];
  vi.spyOn(api, "bootstrap").mockResolvedValue(); vi.spyOn(api, "projects").mockResolvedValue({ items: projects });
  vi.spyOn(api, "profiles").mockResolvedValue({ items: [] }); vi.spyOn(api, "knowledgeBases").mockResolvedValue({ items: [] });
  vi.spyOn(api, "skillRoot").mockResolvedValue({ root: "" } as never); vi.spyOn(api, "skills").mockResolvedValue({ items: [] });
  vi.spyOn(api, "mcpServers").mockResolvedValue({ items: [] }); vi.spyOn(api, "tools").mockResolvedValue({ items: [] });
  vi.spyOn(api, "conversations").mockResolvedValue({ items: [] });
  let finish!: (value: never) => void; vi.spyOn(api, "createConversation").mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  vi.spyOn(api, "messages").mockResolvedValue({ items: [] }); vi.spyOn(api, "events").mockImplementation(async function* () {});
  render(<App api={api} />); await screen.findByRole("button", { name: "项目A" });
  fireEvent.change(screen.getByLabelText("新对话名称"), { target: { value: "A迟到聊天" } });
  // Testing Library can target the closed creation form; native browser behavior is covered separately.
  fireEvent.submit(screen.getByLabelText("新对话名称").closest("form")!);
  fireEvent.click(screen.getByRole("button", { name: "项目B" }));
  await act(async () => { finish({ id: "late", project_id: "a", title: "A迟到聊天", archived: false, selected_profile_id: null } as never); });
  expect(screen.queryByRole("heading", { name: "A迟到聊天" })).toBeNull();
});
