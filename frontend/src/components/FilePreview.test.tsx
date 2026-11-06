import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ApiClient } from "../api/client";
import { FilePreviewProvider, useFilePreview } from "./FilePreview";

function OpenFile() { const preview = useFilePreview(); return <button onClick={() => preview?.openFile({ name: "results.csv", url: "/api/v1/runs/r/artifacts/f" })}>打开结果</button>; }
test("files open on demand, render escaped text, and close without cancelling work", async () => {
  const api = new ApiClient(); const cancel = vi.spyOn(api, "cancelRun");
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('feature_id,value\n<script>bad()</script>,1', { headers: { "content-type": "text/csv" } }));
  render(<FilePreviewProvider api={api} files={[]}><OpenFile /></FilePreviewProvider>);
  expect(screen.queryByRole("complementary", { name: "文件预览" })).toBeNull();
  fireEvent.click(screen.getByText("打开结果"));
  await screen.findByText("<script>bad()</script>"); expect(document.querySelector("script")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "关闭文件预览" }));
  await waitFor(() => expect(screen.queryByRole("complementary", { name: "文件预览" })).toBeNull());
  expect(cancel).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});

test("switching files discards a late response from the previously opened file", async () => {
  const api = new ApiClient(); let finish!: (value: { blob: Blob; type: string }) => void;
  vi.spyOn(api, "readArtifact").mockImplementation((url) => url.endsWith("/old") ? new Promise((resolve) => { finish = resolve; }) : Promise.resolve({ blob: new Blob(["new file"]), type: "text/plain" }));
  function Controls() { const preview = useFilePreview(); return <><button onClick={() => preview?.openFile({ name: "old.txt", url: "/api/v1/runs/r/artifacts/old" })}>旧文件</button><button onClick={() => preview?.openFile({ name: "new.txt", url: "/api/v1/runs/r/artifacts/new" })}>新文件</button></>; }
  render(<FilePreviewProvider api={api} files={[]}><Controls /></FilePreviewProvider>);
  fireEvent.click(screen.getByText("旧文件")); fireEvent.click(screen.getByText("新文件")); await screen.findByText("new file");
  await act(async () => { finish({ blob: new Blob(["old secret"]), type: "text/plain" }); }); expect(screen.queryByText("old secret")).toBeNull();
});
