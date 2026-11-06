import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";

describe("ApiClient", () => {
  afterEach(() => vi.restoreAllMocks());
  it("rejects arbitrary preview URLs and enforces the streamed preview byte limit", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch"); const api = new ApiClient(); const signal = new AbortController().signal;
    await expect(api.readArtifact("https://evil.example/file", signal)).rejects.toThrow("非受控");
    expect(fetcher).not.toHaveBeenCalled();
    fetcher.mockResolvedValue(new Response(new Uint8Array(8 * 1024 * 1024 + 1)));
    await expect(api.readArtifact("/api/v1/runs/r/artifacts/file", signal)).rejects.toThrow("8 MiB");
  });
  it("sends the exact clarification revision so stale responses remain rejectable", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({id:"t1",status:"QUEUED",run_id:null,input_revision:4,pending_input:null}), {status:202, headers:{"Content-Type":"application/json"}}));
    await new ApiClient().respondToTurn("t1", "r1", 3, "Control"); const request = fetchMock.mock.calls[0][1] as RequestInit; expect(JSON.parse(String(request.body))).toMatchObject({request_id:"r1", revision:3, action:"clarify", value:"Control"});
  });
  it("maps a stale revision conflict to a stable ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({detail:{code:"INPUT_RESPONSE_CONFLICT"}}), {status:409, headers:{"Content-Type":"application/json"}}));
    await expect(new ApiClient().respondToTurn("t1", "old", 1, "Control")).rejects.toMatchObject({code:"INPUT_RESPONSE_CONFLICT", status:409});
  });
  it("submits GEO selection with the preview revision and hash", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ id: "import-1" }), { status: 202, headers: { "Content-Type": "application/json" } }));
    await new ApiClient().submitGeoSelection("import-1", { source_id: "source-1", candidate_id: "candidate-1", raw_sha256: "a".repeat(64), feature_column: "feature_id", sample_columns: ["GSM1"], sample_map: { GSM1: "GSM1" }, groups: { GSM1: "AD" }, group_factor: "condition", numerator: "AD", denominator: "Control", revision: 2, evidence: ["confirmed"] });
    expect(fetchMock.mock.calls[0][0]).toContain("/geo/imports/import-1/selection");
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toMatchObject({ revision: 2, raw_sha256: "a".repeat(64) });
  });
});
