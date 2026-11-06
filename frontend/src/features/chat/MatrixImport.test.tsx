import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ApiClient } from "../../api/client";
import { MatrixImport, type MatrixDraft } from "./MatrixImport";

const original: MatrixDraft = { id: "matrix-A", revision: 1, status: "DRAFT", sha256: "hash-A", headers: ["gene", "A", "B", "C", "D"], row_count: 4, preview: [["g1", "1", "2", "3", "4"]] };
const chooseFile = (name: string) => fireEvent.change(screen.getByLabelText("单表达矩阵文件"), { target: { files: [new File(["counts"], name)] } });
const fillConfirmation = (samples = ["A", "B", "C", "D"]) => {
  samples.forEach((sample, index) => fireEvent.change(screen.getByLabelText(`分组 ${sample}`), { target: { value: index < 2 ? "control" : "treated" } }));
  for (const [label, value] of [["实验组", "treated"], ["对照组", "control"], ["矩阵来源", "raw counts source"], ["矩阵研究目标", "compare treated and control"]]) fireEvent.change(screen.getByLabelText(label), { target: { value } });
  fireEvent.change(screen.getByLabelText("数据类型"), { target: { value: "RAW_COUNTS" } });
};

test("failed replacement removes the previous matrix and allows retrying the same file", async () => {
  const api = new ApiClient(); const confirmed = vi.fn();
  vi.spyOn(api, "matrixLatest").mockResolvedValue(null);
  let rejectUpload!: (reason: Error) => void;
  const replacement = { ...original, id: "matrix-B", sha256: "hash-B" };
  const upload = vi.spyOn(api, "matrixUpload").mockResolvedValueOnce(original).mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectUpload = reject; })).mockResolvedValueOnce(replacement);
  const confirm = vi.spyOn(api, "matrixConfirm").mockResolvedValue({ ...replacement, status: "CONFIRMED" });
  vi.spyOn(api, "matrixResults").mockResolvedValue({ status: "AWAITING_APPROVAL" });
  render(<MatrixImport api={api} chat="a" profile="p" onConfirmed={confirmed} />);
  await act(async () => { chooseFile("A.csv"); }); fillConfirmation();
  await act(async () => { chooseFile("B.csv"); });
  expect(screen.getByLabelText("单表达矩阵文件")).toBeDisabled();
  await act(async () => { rejectUpload(new Error("MATRIX_UPLOAD_FAILED")); });
  expect(screen.getByRole("alert")).toHaveTextContent("MATRIX_UPLOAD_FAILED");
  expect(screen.queryByText(/hash-A/)).toBeNull();
  expect(screen.queryByRole("button", { name: "确认分组并生成待审批方案" })).toBeNull();
  expect(screen.queryByLabelText("分组 A")).toBeNull(); expect(confirm).not.toHaveBeenCalled();
  expect(screen.getByLabelText("单表达矩阵文件")).toHaveValue("");
  await act(async () => { chooseFile("B.csv"); });
  expect(upload).toHaveBeenCalledTimes(3); expect(screen.getByLabelText("分组 A")).toHaveValue("");
  fillConfirmation();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "确认分组并生成待审批方案" })); });
  expect(confirm).toHaveBeenCalledWith("a", "matrix-B", expect.objectContaining({ direction: "genes_rows", groups: { "1": "control", "2": "control", "3": "treated", "4": "treated" } }));
  expect(confirmed).toHaveBeenCalledWith(expect.objectContaining({ id: "matrix-B" }));
});

test("failed transpose retains the original direction and mappings until a successful retry", async () => {
  const api = new ApiClient();
  vi.spyOn(api, "matrixLatest").mockResolvedValue(null);
  vi.spyOn(api, "matrixUpload").mockResolvedValue(original);
  let rejectPreview!: (reason: Error) => void;
  const transposed = { ...original, headers: ["gene", "g1", "g2", "g3", "g4"], preview: [["A", "1", "2", "3", "4"]] };
  const preview = vi.spyOn(api, "matrixPreview").mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectPreview = reject; })).mockResolvedValueOnce(transposed);
  const confirm = vi.spyOn(api, "matrixConfirm").mockResolvedValue({ ...transposed, status: "CONFIRMED" });
  vi.spyOn(api, "matrixResults").mockResolvedValue({ status: "AWAITING_APPROVAL" });
  render(<MatrixImport api={api} chat="a" profile="p" onConfirmed={vi.fn()} />);
  await act(async () => { chooseFile("A.csv"); }); fillConfirmation();
  await act(async () => { fireEvent.change(screen.getByLabelText("矩阵方向"), { target: { value: "samples_rows" } }); });
  expect(screen.getByRole("button", { name: "确认分组并生成待审批方案" })).toBeDisabled();
  await act(async () => { rejectPreview(new Error("PREVIEW_TIMEOUT")); });
  expect(screen.getByLabelText("矩阵方向")).toHaveValue("genes_rows");
  expect(screen.getByLabelText("分组 A")).toHaveValue("control");
  expect(screen.getByRole("columnheader", { name: "A" })).toBeInTheDocument();
  expect(confirm).not.toHaveBeenCalled();
  await act(async () => { fireEvent.change(screen.getByLabelText("矩阵方向"), { target: { value: "samples_rows" } }); });
  expect(preview).toHaveBeenCalledTimes(2); expect(screen.getByLabelText("矩阵方向")).toHaveValue("samples_rows");
  expect(screen.queryByLabelText("分组 A")).toBeNull(); expect(screen.getByLabelText("分组 g1")).toHaveValue("");
  fillConfirmation(["g1", "g2", "g3", "g4"]);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "确认分组并生成待审批方案" })); });
  expect(confirm).toHaveBeenCalledWith("a", "matrix-A", expect.objectContaining({ direction: "samples_rows", sample_columns: [1, 2, 3, 4], groups: { "1": "control", "2": "control", "3": "treated", "4": "treated" } }));
});

test("a late transpose preview cannot change a newly mounted conversation", async () => {
  const api = new ApiClient();
  vi.spyOn(api, "matrixLatest").mockImplementation(async (chat) => chat === "a" ? original : { ...original, id: "matrix-B", sha256: "hash-B" });
  let finish!: (value: MatrixDraft) => void;
  vi.spyOn(api, "matrixPreview").mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  const previous = render(<MatrixImport api={api} chat="a" profile="p" onConfirmed={vi.fn()} />);
  await screen.findByLabelText("分组 A");
  fireEvent.change(screen.getByLabelText("矩阵方向"), { target: { value: "samples_rows" } });
  previous.unmount();
  render(<MatrixImport api={api} chat="b" profile="p" onConfirmed={vi.fn()} />);
  await screen.findByText(/hash-B/);
  await act(async () => { finish({ ...original, headers: ["gene", "late1", "late2"] }); });
  expect(screen.getByLabelText("矩阵方向")).toHaveValue("genes_rows");
  expect(screen.queryByLabelText("分组 late1")).toBeNull(); expect(screen.getByLabelText("分组 A")).toHaveValue("");
});

test("a confirmed matrix still restores its analysis without resubmitting confirmation", async () => {
  const api = new ApiClient(); const confirmed = vi.fn();
  const saved = { ...original, status: "CONFIRMED", dataset_id: "dataset-A", turn_id: "turn-A", run_id: "run-A" };
  vi.spyOn(api, "matrixLatest").mockResolvedValue(saved);
  vi.spyOn(api, "matrixResults").mockResolvedValue({ status: "AWAITING_APPROVAL" });
  const confirm = vi.spyOn(api, "matrixConfirm");
  render(<MatrixImport api={api} chat="a" profile="p" onConfirmed={confirmed} />);
  fireEvent.click(await screen.findByRole("button", { name: "恢复此分析" }));
  expect(confirmed).toHaveBeenCalledWith(saved); expect(confirm).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "确认分组并生成待审批方案" })).toBeNull();
});

test("replacing a matrix clears old mappings and unmount discards late confirmation", async () => {
  const api = new ApiClient(); const confirmed = vi.fn();
  vi.spyOn(api, "matrixLatest").mockResolvedValue(null);
  vi.spyOn(api, "matrixUpload").mockResolvedValue({ id:"x",revision:1,status:"DRAFT",sha256:"hash",headers:["gene","A","B","C","D"],row_count:1,preview:[["g","1","2","3","4"]] });
  const { unmount } = render(<MatrixImport api={api} chat="a" profile="p" onConfirmed={confirmed} />);
  const choose = () => fireEvent.change(screen.getByLabelText("单表达矩阵文件"), { target: { files: [new File(["a"],"m.csv")] } });
  await act(async () => { choose(); }); fireEvent.change(screen.getByLabelText("分组 A"), {target:{value:"old"}});
  await act(async () => { choose(); }); expect(screen.getByLabelText("分组 A")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("数据类型"), {target:{value:"RAW_COUNTS"}}); fireEvent.change(screen.getByLabelText("矩阵来源"),{target:{value:"synthetic"}}); fireEvent.change(screen.getByLabelText("矩阵研究目标"),{target:{value:"test"}});
  let finish!: (value: never) => void; vi.spyOn(api,"matrixConfirm").mockImplementation(() => new Promise((resolve) => {finish=resolve;}));
  fireEvent.click(screen.getByRole("button",{name:"确认分组并生成待审批方案"})); expect(screen.getByLabelText("实验组")).toBeDisabled();
  unmount(); await act(async () => { finish({id:"x",status:"CONFIRMED"} as never); }); expect(confirmed).not.toHaveBeenCalled();
});
