import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ModelSettings } from "./ModelSettings";

describe("ModelSettings", () => { it("clears the credential input after saving", () => { const onSave=vi.fn(); render(<ModelSettings onSave={onSave}/>); const input=screen.getByLabelText("API Key"); fireEvent.change(input,{target:{value:"virtual-key"}}); fireEvent.click(screen.getByRole("button",{name:"保存模型"})); expect(onSave).toHaveBeenCalledWith(expect.objectContaining({apiKey:"virtual-key"})); expect(input).toHaveValue(""); expect(localStorage.getItem("api_key")).toBeNull(); }); });
it("lists profiles and supports selection, edit, delete, clear credential, and probe", async () => { const onSelect=vi.fn(); const onUpdate=vi.fn(); const onDelete=vi.fn(); const onClear=vi.fn(); const onProbe=vi.fn(); render(<ModelSettings onSave={vi.fn()} profiles={[{id:"p1", label:"DeepSeek", provider:"deepseek", model:"deepseek-chat", base_url:"https://api.deepseek.com", credential_configured:true, revision:2}]} selectedProfileId="p1" onSelectProfile={onSelect} onUpdate={onUpdate} onDelete={onDelete} onClearCredential={onClear} onProbe={onProbe} />); expect(screen.getByLabelText("已保存模型")).toHaveTextContent("DeepSeek"); fireEvent.click(screen.getByRole("button", {name:"探测连接"})); await waitFor(() => expect(screen.getByRole("button", {name:"清除凭据"})).toBeEnabled()); fireEvent.click(screen.getByRole("button", {name:"清除凭据"})); await waitFor(() => expect(screen.getByRole("button", {name:"删除模型"})).toBeEnabled()); fireEvent.click(screen.getByRole("button", {name:"删除模型"})); await waitFor(() => expect(screen.getByRole("button", {name:"更新模型"})).toBeEnabled()); fireEvent.click(screen.getByRole("button", {name:"更新模型"})); expect(onProbe).toHaveBeenCalledWith("p1"); expect(onClear).toHaveBeenCalledWith("p1"); expect(onDelete).toHaveBeenCalledWith("p1", 2); expect(onUpdate).toHaveBeenCalled(); });

it("explains that environment profiles are read-only and resets the new-profile form", () => {
  const profile = {id:"env", label:"Environment / deepseek", provider:"deepseek", model:"deepseek-chat", base_url:"https://api.deepseek.com", credential_configured:true, revision:1, read_only:true};
  const { rerender } = render(<ModelSettings onSave={vi.fn()} profiles={[profile]} selectedProfileId="env" />);
  expect(screen.getByLabelText("API Key")).toBeDisabled();
  expect(screen.getByText(/BIOAGENT_DEEPSEEK_API_KEY/)).toBeInTheDocument();
  rerender(<ModelSettings onSave={vi.fn()} profiles={[profile]} selectedProfileId="" />);
  expect(screen.getByLabelText("API Key")).toBeEnabled();
  expect(screen.getByLabelText("模型")).toHaveValue("");
});

it("blocks duplicate saves and reports a credential persistence failure", async () => {
  let rejectSave: (error: Error) => void = () => undefined;
  const onSave = vi.fn(() => new Promise<void>((_resolve, reject) => { rejectSave = reject; }));
  render(<ModelSettings onSave={onSave} />);
  fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "synthetic-key" } });
  const save = screen.getByRole("button", { name: "保存模型" });
  fireEvent.click(save);
  expect(save).toBeDisabled();
  fireEvent.click(save);
  expect(onSave).toHaveBeenCalledTimes(1);
  rejectSave(new Error("凭据保存失败，请重试"));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("凭据保存失败"));
  expect(save).toBeEnabled();
  expect(screen.getByLabelText("API Key")).toHaveValue("");
});
