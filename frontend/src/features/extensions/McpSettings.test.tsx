import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { McpSettings } from "./McpSettings";

it("clears a credential value after saving and requires a saved server before connect", () => {
  const onSave = vi.fn();
  const onConnect = vi.fn();
  render(<McpSettings servers={[]} onSave={onSave} onConnect={onConnect} />);

  const credential = screen.getByLabelText("凭据值");
  expect(screen.getByRole("button", { name: "连接" })).toBeDisabled();
  fireEvent.change(credential, { target: { value: "secret-never-rendered" } });
  fireEvent.click(screen.getByRole("button", { name: "保存 MCP 服务" }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ credentialValue: "secret-never-rendered" }));
  expect(credential).toHaveValue("");
  expect(document.body.textContent).not.toContain("secret-never-rendered");
});

it("loads and updates a saved stdio server without splitting arguments on spaces", () => {
  const onSave = vi.fn();
  render(<McpSettings servers={[{
    id: "server-1", label: "本地只读", transport: "stdio", enabled: true, revision: 3,
    stdio: { executable: "C:\\Program Files\\Python\\python.exe", argv: ["C:\\My Project\\server.py", "--read-only"], cwd: "C:\\My Project", env_refs: {} },
  }]} onSave={onSave} onConnect={vi.fn()} />);

  fireEvent.change(screen.getByLabelText("已保存 MCP 服务"), { target: { value: "server-1" } });
  expect(screen.getByLabelText("绝对程序路径")).toHaveValue("C:\\Program Files\\Python\\python.exe");
  expect(screen.getByLabelText("参数 argv（每行一项）")).toHaveValue("C:\\My Project\\server.py\n--read-only");
  fireEvent.click(screen.getByRole("button", { name: "保存 MCP 服务" }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ serverId: "server-1", revision: 3, argv: ["C:\\My Project\\server.py", "--read-only"] }));
});
