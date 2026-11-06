import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ApiClient } from "../../api/client";
import { KnowledgeManager } from "./KnowledgeManager";

const limits = { max_pdf_bytes: 50 * 1024 ** 2, max_files_per_request: 4, max_files_per_selection: 100, max_request_bytes: 201 * 1024 ** 2 };
function setup() {
  const api = Object.assign(new ApiClient(), { knowledgeUploadLimits: vi.fn(async () => limits) });
  vi.spyOn(api, "knowledgeBases").mockResolvedValue({ items: [{ id: "base", name: "测试库" }] });
  vi.spyOn(api, "knowledgeReadiness").mockResolvedValue({ ready: true, code: "OK" });
  vi.spyOn(api, "knowledgeDocuments").mockResolvedValue({ items: [] });
  const upload = vi.spyOn(api, "uploadKnowledgeDocuments").mockResolvedValue({ items: [] });
  return { api, upload };
}
function choose(files: File[]) { fireEvent.change(screen.getByLabelText("本地 PDF"), { target: { files } }); }
function file(name: string, size = 100) { const value = new File(["%PDF-fixture"], name, { type: "application/pdf" }); Object.defineProperty(value, "size", { value: size }); return value; }

test("explains per-file limits, skips oversize files, accepts 12 MiB and rejects 101 selections", async () => {
  const { api, upload } = setup();
  render(<KnowledgeManager api={api} onChanged={() => {}} onClose={() => {}} />);
  await screen.findByLabelText("本地 PDF");
  choose([file("oversize.pdf", limits.max_pdf_bytes + 10486)]);
  expect(screen.getByRole("button", { name: "上传并解析" })).toBeDisabled();
  choose([file("oversize.pdf", limits.max_pdf_bytes + 10486), file("valid.pdf", 12 * 1024 ** 2)]);
  expect(await screen.findByText(/oversize.pdf.*50.01 MiB.*超过单份 50 MiB/)).toBeVisible();
  expect(screen.getByText(/valid.pdf.*12.00 MiB/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "上传并解析" }));
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
  expect(upload.mock.calls[0][1].map((item) => item.name)).toEqual(["valid.pdf"]);
  await waitFor(() => expect(screen.getByLabelText("本地 PDF")).toBeEnabled());
  choose([file("boundary.pdf", limits.max_pdf_bytes)]);
  expect(screen.getByRole("button", { name: "上传并解析" })).toBeEnabled();
  choose(Array.from({ length: 101 }, (_, index) => file(`${index}.pdf`)));
  expect(screen.getByText(/已选择 101 份，超过每次最多 100 份/)).toBeVisible();
  expect(screen.getByRole("button", { name: "上传并解析" })).toBeDisabled();
});

test("uploads 100 files serially, continues after failure and retries only the failed file", async () => {
  const { api, upload } = setup();
  upload.mockRejectedValueOnce(new Error("fixture failure"));
  render(<KnowledgeManager api={api} onChanged={() => {}} onClose={() => {}} />);
  await screen.findByLabelText("本地 PDF");
  choose(Array.from({ length: 100 }, (_, index) => file(`paper-${index}.pdf`)));
  fireEvent.click(screen.getByRole("button", { name: "上传并解析" }));
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(100));
  expect(upload.mock.calls.every(([base, files]) => base === "base" && files.length === 1)).toBe(true);
  expect(screen.getByText(/已上传 99\/100/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "重试失败文件" }));
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(101));
  expect(upload.mock.calls[100][1][0].name).toBe("paper-0.pdf");
  await screen.findByText(/已上传 100\/100/);
});

test("parser readiness survives retrieval failure and explains pending parser state", async () => {
  const { api } = setup();
  let ready!: (value: { ready: boolean; code: string }) => void;
  vi.mocked(api.knowledgeReadiness).mockImplementation((retrieval) => retrieval ? Promise.reject(new Error("offline")) : new Promise((resolve) => { ready = resolve; }));
  render(<KnowledgeManager api={api} onChanged={() => {}} onClose={() => {}} />);
  await screen.findByLabelText("本地 PDF");
  expect(screen.getByText(/正在检查本地解析状态/)).toBeVisible();
  ready({ ready: true, code: "OK" });
  await waitFor(() => expect(screen.getByLabelText("本地 PDF")).toBeEnabled());
  expect(screen.getByText(/本地检索状态读取失败/)).toBeVisible();
  choose([file("valid.pdf")]);
  expect(screen.getByRole("button", { name: "上传并解析" })).toBeEnabled();
});

test("stop and unmount prevent pending uploads while keeping the target library fixed", async () => {
  const { api, upload } = setup(); let finish!: () => void;
  upload.mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve({ items: [] }); }));
  const onChanged = vi.fn();
  const { unmount } = render(<KnowledgeManager api={api} onChanged={onChanged} onClose={() => {}} />);
  await screen.findByLabelText("本地 PDF"); choose([file("one.pdf"), file("two.pdf"), file("three.pdf")]);
  fireEvent.click(screen.getByRole("button", { name: "上传并解析" }));
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
  expect(screen.getByLabelText("管理知识库")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "停止后续上传" })); finish();
  await waitFor(() => expect(screen.getByLabelText("本地 PDF")).toBeEnabled());
  expect(upload).toHaveBeenCalledTimes(1);
  expect(within(screen.getByRole("list", { name: "所选 PDF" })).getByText(/two.pdf.*尚未上传/)).toBeVisible();
  upload.mockImplementationOnce(() => new Promise((resolve) => { finish = () => resolve({ items: [] }); }));
  fireEvent.click(screen.getByRole("button", { name: "上传并解析" }));
  await waitFor(() => expect(upload).toHaveBeenCalledTimes(2));
  unmount(); finish();
  await Promise.resolve(); expect(upload).toHaveBeenCalledTimes(2); expect(onChanged).toHaveBeenCalledTimes(1);
});
