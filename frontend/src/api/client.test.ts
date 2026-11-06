import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";

describe("ApiClient", () => {
  afterEach(() => vi.restoreAllMocks());
  it("sends the exact clarification revision so stale responses remain rejectable", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({id:"t1",status:"QUEUED",run_id:null,input_revision:4,pending_input:null}), {status:202, headers:{"Content-Type":"application/json"}}));
    await new ApiClient().respondToTurn("t1", "r1", 3, "Control"); const request = fetchMock.mock.calls[0][1] as RequestInit; expect(JSON.parse(String(request.body))).toMatchObject({request_id:"r1", revision:3, action:"clarify", value:"Control"});
  });
  it("maps a stale revision conflict to a stable ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({detail:{code:"INPUT_RESPONSE_CONFLICT"}}), {status:409, headers:{"Content-Type":"application/json"}}));
    await expect(new ApiClient().respondToTurn("t1", "old", 1, "Control")).rejects.toMatchObject({code:"INPUT_RESPONSE_CONFLICT", status:409});
  });
});
