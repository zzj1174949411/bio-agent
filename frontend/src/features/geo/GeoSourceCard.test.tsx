import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GeoSourceCard } from "./GeoSourceCard";

const candidates = [
  { id: "raw", file_name: "counts.tsv.gz", data_kind: "RAW_COUNTS" as const, size_bytes: 1200, evidence: ["integer count matrix"], compression: "GZIP" as const },
  { id: "tpm", file_name: "TPM.tsv", data_kind: "NORMALIZED" as const, size_bytes: null, evidence: ["提交者注明 TPM"], compression: "NONE" as const },
  { id: "unknown", file_name: "matrix.txt", data_kind: "UNKNOWN" as const, size_bytes: null, evidence: ["类型未声明"], compression: "NONE" as const },
];

describe("GeoSourceCard", () => {
  it("never offers normalized data as raw counts", () => {
    render(<GeoSourceCard candidates={candidates} onConfirm={vi.fn()} />);
    expect(screen.getByRole("button", { name: "下载 TPM.tsv" })).toBeDisabled();
  });

  it("requires an explicit raw-count declaration for UNKNOWN candidates", () => {
    const onConfirm = vi.fn();
    render(<GeoSourceCard candidates={candidates} onConfirm={onConfirm} />);
    const download = screen.getByRole("button", { name: "下载 matrix.txt" });
    expect(download).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "确认 matrix.txt 是原始 counts" }));
    expect(download).toBeEnabled();
    fireEvent.click(download);
    expect(onConfirm).toHaveBeenCalledWith("unknown", true);
  });

  it("shows source evidence, limits, and an unknown size without inventing a size", () => {
    render(<GeoSourceCard accession="GSE123" title="study" organisms={["Homo sapiens"]} platforms={["GPL1"]} officialUrl="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE123" maxBytes={5000} candidates={candidates} onConfirm={vi.fn()} />);
    expect(screen.getByText("GSE123")).toBeInTheDocument();
    expect(screen.getAllByText(/大小未知/)).not.toHaveLength(0);
    expect(screen.getByText(/上限 5,000 B/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看官方记录" })).toHaveAttribute("href", expect.stringContaining("GSE123"));
  });

  it("explains when discovery found no importable counts candidate", () => {
    render(<GeoSourceCard candidates={[candidates[1]]} onConfirm={vi.fn()} />);
    expect(screen.getByText("没有可下载的原始 counts 候选文件。")).toBeInTheDocument();
  });
});
