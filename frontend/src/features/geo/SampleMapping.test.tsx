import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GeoImportProgress } from "./GeoImportProgress";
import { SampleMapping } from "./SampleMapping";

const source = {
  id: "source-1", accession: "GSE123", samples: [
    { accession: "GSM1", characteristics: [{ name: "disease", value: "AD" }] },
    { accession: "GSM2", characteristics: [{ name: "disease", value: "AD" }] },
    { accession: "GSM3", characteristics: [{ name: "disease", value: "Control" }] },
    { accession: "GSM4", characteristics: [{ name: "disease", value: "Control" }] },
  ],
};
const imported = {
  id: "import-1", source_id: "source-1", candidate_id: "candidate-1", revision: 2,
  status: "AWAITING_MAPPING", raw_sha256: "a".repeat(64),
  preview: { feature_columns: ["feature_id"], sample_columns: ["col1", "col2", "col3", "col4"], suggested_sample_map: { col1: "GSM1", col2: "GSM2", col3: "GSM3", col4: "GSM4" } },
};

describe("SampleMapping", () => {
  it("keeps a corrected duplicate mapping visible and blocks submission", () => {
    const onSubmit = vi.fn();
    render(<SampleMapping source={source} imported={imported} onSubmit={onSubmit} onBack={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("矩阵列 col2 对应 GSM"), { target: { value: "GSM1" } });
    expect(screen.getByRole("alert")).toHaveTextContent("每个 GSM 只能映射一次");
    expect(screen.getByLabelText("矩阵列 col2 对应 GSM")).toHaveValue("GSM1");
    expect(screen.getByRole("button", { name: "确认样本映射" })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("requires exactly two groups with at least two included samples and states direction", () => {
    render(<SampleMapping source={source} imported={imported} onSubmit={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByText(/AD 相对 Control/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("GSM4 分组"), { target: { value: "Other" } });
    expect(screen.getByRole("alert")).toHaveTextContent("请选择恰好两个分组");
    expect(screen.getByRole("button", { name: "确认样本映射" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("GSM4 分组"), { target: { value: "Control" } });
    fireEvent.change(screen.getByLabelText("GSM2 分组"), { target: { value: "Control" } });
    expect(screen.getByRole("alert")).toHaveTextContent("每组至少需要 2 个样本");
  });

  it("requires reconfirmation when a new raw hash or revision replaces the preview", () => {
    const { rerender } = render(<SampleMapping source={source} imported={imported} onSubmit={vi.fn()} onBack={vi.fn()} />);
    rerender(<SampleMapping source={source} imported={{ ...imported, revision: 3, raw_sha256: "b".repeat(64) }} onSubmit={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("来源文件或 revision 已更新，请重新确认映射");
  });

  it("retains edits after a server validation error and provides a route back to candidates", () => {
    const onBack = vi.fn();
    render(<SampleMapping source={source} imported={imported} errorCode="SOURCE_CHANGED" onSubmit={vi.fn()} onBack={onBack} />);
    fireEvent.change(screen.getByLabelText("矩阵列 col1 对应 GSM"), { target: { value: "GSM2" } });
    expect(screen.getByText("SOURCE_CHANGED")).toBeInTheDocument();
    expect(screen.getByLabelText("矩阵列 col1 对应 GSM")).toHaveValue("GSM2");
    fireEvent.click(screen.getByRole("button", { name: "返回候选文件" }));
    expect(onBack).toHaveBeenCalledOnce();
  });
});

describe("GeoImportProgress", () => {
  it("does not fabricate a percentage when the source size is unknown and reports cancellation", () => {
    const onCancel = vi.fn();
    const { rerender } = render(<GeoImportProgress status="DOWNLOADING" bytesDownloaded={2048} totalBytes={null} onCancel={onCancel} />);
    expect(screen.getByText("已下载 2,048 B（总大小未知）")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "取消下载" }));
    expect(onCancel).toHaveBeenCalledOnce();
    rerender(<GeoImportProgress status="CANCELLED" bytesDownloaded={2048} totalBytes={null} onCancel={onCancel} />);
    expect(screen.getByText("下载已取消")).toBeInTheDocument();
  });
});
