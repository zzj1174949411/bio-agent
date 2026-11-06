import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { expect, test, vi } from "vitest";
import { ApiClient } from "../../api/client";
import { ChatWorkspace, emptyDraft, type ChatDraft } from "./ChatWorkspace";

const chat = (id: string) => ({ id, project_id: "p", title: id, archived: false, selected_profile_id: "model" });
function apiFixture() {
  const api = new ApiClient();
  vi.spyOn(api, "messages").mockResolvedValue({ items: [] });
  vi.spyOn(api, "events").mockImplementation(async function* () {});
  vi.spyOn(api, "submitTurn").mockResolvedValue({ id: "t", status: "WAITING_USER", run_id: "r", input_revision: 0, pending_input: null });
  vi.spyOn(api, "runPlan").mockResolvedValue({ run_id: "r", plan_revision: 7, plan: { comparison: { factor: "condition", numerator: "treated", denominator: "control" }, options: { alpha: 0.05 } } });
  vi.spyOn(api, "run").mockResolvedValue({ status: "AWAITING_APPROVAL" });
  vi.spyOn(api, "artifacts").mockResolvedValue({ run_id: "r", artifacts: [{ artifact_id: "file", sha256: "hash", name: "results.csv", media_type: "text/csv" }] } as never);
  vi.spyOn(api, "approveRun").mockResolvedValue({ status: "QUEUED" });
  vi.spyOn(api, "cancelRun").mockResolvedValue({ status: "CANCELLED" });
  return api;
}
const profiles = [{ id: "model", label: "Mock", provider: "ollama", model: "mock", base_url: "http://localhost", credential_configured: false }];
function Harness({ api }: { api: ApiClient }) {
  const [id, setId] = useState("a"); const [drafts, setDrafts] = useState<Record<string, ChatDraft>>({});
  return <><button onClick={() => setId("a")}>聊天A</button><button onClick={() => setId("b")}>聊天B</button><ChatWorkspace key={id} api={api} conversation={chat(id)} profiles={profiles} knowledgeBases={[]} draft={drafts[id] ?? emptyDraft()} onDraftChange={(draft) => setDrafts((current) => ({ ...current, [id]: draft }))} onConversationChange={vi.fn()} onOpenSettings={vi.fn()} onOpenKnowledge={vi.fn()} /></>;
}

test("drafts, import files and late responses belong to their conversation", async () => {
  const api = apiFixture(); let resolveA!: (value: never) => void;
  vi.mocked(api.messages).mockImplementation((id) => id === "a" ? new Promise((resolve) => { resolveA = resolve; }) : Promise.resolve({ items: [] }));
  render(<Harness api={api} />);
  fireEvent.change(screen.getByLabelText("消息"), { target: { value: "A草稿" } });
  fireEvent.click(screen.getByRole("button", { name: "添加" })); fireEvent.click(screen.getByRole("button", { name: "导入分析数据" }));
  fireEvent.change(screen.getByLabelText("counts 文件"), { target: { files: [new File(["a"], "a.csv")] } });
  fireEvent.click(screen.getByText("聊天B"));
  expect(screen.getByLabelText("消息")).toHaveValue("");
  expect(screen.queryByText("a.csv")).toBeNull();
  resolveA({ items: [{ id: "late", role: "assistant", content: "A迟到消息", dataset_ids: [], partial: false }] } as never);
  await waitFor(() => expect(screen.queryByText("A迟到消息")).toBeNull());
  fireEvent.click(screen.getByText("聊天A"));
  expect(screen.getByLabelText("消息")).toHaveValue("A草稿");
  fireEvent.click(screen.getByRole("button", { name: "添加" })); fireEvent.click(screen.getByRole("button", { name: "导入分析数据" }));
  expect(screen.getByText("a.csv")).toBeInTheDocument();
});

test("restores an existing run, requires explicit approval and cancels the real run", async () => {
  const api = apiFixture();
  vi.mocked(api.messages).mockResolvedValue({ items: [{ id: "m", role: "assistant", turn_id: "t", content: "已准备计划", partial: false, dataset_ids: [] }] });
  vi.spyOn(api, "turn").mockResolvedValue({ id: "t", status: "WAITING_USER", run_id: "r", input_revision: 0, pending_input: null });
  render(<Harness api={api} />);
  expect(screen.queryByRole("complementary", { name: "文件预览" })).toBeNull();
  const approve = await screen.findByRole("button", { name: "批准分析" });
  expect(approve).toBeDisabled(); expect(api.approveRun).not.toHaveBeenCalled();
  expect(screen.getByText(/treated 相对 control/)).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("我已核对本次方案"));
  vi.mocked(api.run).mockResolvedValue({ status: "RUNNING" }); fireEvent.click(approve);
  await waitFor(() => expect(api.approveRun).toHaveBeenCalledWith("r", 7));
  fireEvent.click(await screen.findByRole("button", { name: "停止运行" }));
  await waitFor(() => expect(api.cancelRun).toHaveBeenCalledWith("r"));
  expect(api.submitTurn).not.toHaveBeenCalled();
});

test("a late history response does not overwrite a newer SSE message", async () => {
  const api = apiFixture(); let finish!: (value: { items: [] }) => void;
  vi.mocked(api.messages).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  vi.mocked(api.events).mockImplementation(async function* () { yield { seq: 1, kind: "message.completed", payload: { message_id: "new", role: "assistant", text: "新的真实事件", turn_id: "t" } }; });
  render(<Harness api={api} />);
  await screen.findByText("新的真实事件"); await act(async () => { finish({ items: [] }); });
  expect(screen.getByText("新的真实事件")).toBeInTheDocument();
});

test("later ordinary messages do not hide an earlier run's published files on restore", async () => {
  const api = apiFixture();
  vi.mocked(api.messages).mockResolvedValue({ items: [{ id: "new", turn_id: "ordinary", role: "assistant", content: "后续讨论", partial: false, dataset_ids: [] }, { id: "old", turn_id: "analysis", role: "assistant", content: "原分析", partial: false, dataset_ids: [] }] });
  vi.spyOn(api, "turn").mockImplementation(async (id) => ({ id, status: "COMPLETED", run_id: id === "analysis" ? "r" : null, input_revision: 0, pending_input: null }));
  vi.mocked(api.run).mockResolvedValue({ status: "COMPLETED" });
  render(<Harness api={api} />);
  await screen.findByRole("button", { name: "打开 results.csv" });
  vi.mocked(api.submitTurn).mockResolvedValue({ id: "next", status: "RUNNING", run_id: null, input_revision: 0, pending_input: null });
  fireEvent.change(screen.getByLabelText("消息"), { target: { value: "继续讨论" } });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "发送" })); });
  expect(screen.getByLabelText("消息")).toBeDisabled();
});
