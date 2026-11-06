import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { GeoSearchState } from "../../api/types";
import { GeoSearchResults } from "./GeoSearchResults";

const readySearch: GeoSearchState = {
  id: "search-1",
  status: "AWAITING_SELECTION",
  revision: 3,
  query_hash: "a".repeat(64),
  query: {
    text: "AD brain RNA-seq",
    provider: "geo",
    organism: "Homo sapiens",
    tissue: "brain",
    technology: null,
    page_token: null,
    page_size: 10,
  },
  items: [
    {
      provider: "geo",
      source_id: "GSE111",
      title: "<untrusted GEO title>",
      summary: "Untrusted study summary",
      organisms: ["Homo sapiens"],
      platforms: ["GPL1"],
      sample_count: 12,
      published_at: "2026-09-14",
      source_uri: "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE111",
      analysis_readiness: "NEEDS_INSPECTION",
      evidence: {
        provider: "geo",
        source_id: "GSE111",
        source_uri: "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE111",
        retrieved_at: "2026-09-14T00:00:00+00:00",
        content_sha256: "b".repeat(64),
      },
    },
  ],
  result_count: 1,
  total: 11,
  next_page_token: "server-owned-page-token",
  source_id: null,
  error_code: null,
};

describe("GeoSearchResults", () => {
  it("shows normalized untrusted results and selects a server-owned GSE for inspection", () => {
    const onSelect = vi.fn();
    render(
      <GeoSearchResults
        search={readySearch}
        onSelect={onSelect}
        onNext={vi.fn()}
        onCancel={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    expect(screen.getByText("AD brain RNA-seq")).toBeInTheDocument();
    expect(screen.getByText("<untrusted GEO title>")).toBeInTheDocument();
    expect(screen.getByText("还需检查 raw counts 与样本信息。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "检查 GSE111 的可分析文件" }));
    expect(onSelect).toHaveBeenCalledWith("GSE111", readySearch.revision);
  });

  it("uses only the server-issued next-page token", () => {
    const onNext = vi.fn();
    render(
      <GeoSearchResults
        search={readySearch}
        onSelect={vi.fn()}
        onNext={onNext}
        onCancel={vi.fn()}
        onRetry={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(onNext).toHaveBeenCalledWith("server-owned-page-token", readySearch.revision);
  });

  it("shows a stable failure code and allows an explicit retry", () => {
    const onRetry = vi.fn();
    render(
      <GeoSearchResults
        search={{ ...readySearch, status: "FAILED", error_code: "GEO_SEARCH_UNAVAILABLE" }}
        onSelect={vi.fn()}
        onNext={vi.fn()}
        onCancel={vi.fn()}
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText("GEO_SEARCH_UNAVAILABLE")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试搜索" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
