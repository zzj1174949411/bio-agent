import { render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ApiClient } from "../../api/client";
import { KnowledgeAnswer } from "./KnowledgeAnswer";
import { readKnowledgeEvents } from "../../api/knowledge";

test("revokes visible answers and previews when evidence becomes stale; source text stays escaped", async () => {
  const api = new ApiClient();
  const ref = { chunk_id: "chunk", document_id: "doc", page: 1 };
  let stale = false;
  vi.spyOn(api, "knowledgeTask").mockImplementation(async () => stale ? ({ status: "FAILED", error_code: "EVIDENCE_STALE", answer: null, citations: [], evidence: [], fixed_scope: [] } as never) : ({ status: "COMPLETED", answer: "Verified answer <script>bad()</script>", citations: [ref], evidence: [{ reference: ref, chunk: { id: "chunk", kind: "text", text: "<img src=x onerror=bad()>", section: ["Results"] } }], fixed_scope: [] } as never));
  vi.spyOn(api, "knowledgeEvents").mockImplementation(async function* () { yield { sequence: 1, kind: "completed", data: {} }; });
  render(<KnowledgeAnswer api={api} conversationId="chat" turnId="turn" />);
  await screen.findByText(/Verified answer/);
  expect(document.querySelector("script")).toBeNull();
  expect(document.querySelector("img")).toBeNull();
  stale = true;
  window.dispatchEvent(new Event("focus"));
  await screen.findByText(/证据已失效/);
  await waitFor(() => expect(screen.queryByText(/Verified answer/)).toBeNull());
});

test("knowledge SSE resumes the same turn by sequence and suppresses duplicate segments", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  const block = (sequence: number, kind: string, text = "") => `id: ${sequence}\nevent: ${kind}\ndata: ${JSON.stringify({ sequence, kind, data: { text } })}\n\n`;
  fetcher.mockResolvedValueOnce(new Response(block(1, "answer.delta", "a")));
  fetcher.mockResolvedValueOnce(new Response(block(1, "answer.delta", "a") + block(2, "answer.delta", "b") + block(3, "completed")));
  const events = [];
  for await (const event of readKnowledgeEvents("/fixed-chat/fixed-turn/events", new AbortController().signal)) events.push(event);
  expect(events.filter((event) => event.kind === "answer.delta").map((event) => event.data.text).join("")).toBe("ab");
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(["/fixed-chat/fixed-turn/events?after=0", "/fixed-chat/fixed-turn/events?after=1"]);
  fetcher.mockRestore();
});
