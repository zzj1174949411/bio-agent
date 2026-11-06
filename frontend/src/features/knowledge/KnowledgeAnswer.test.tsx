import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { ApiClient } from "../../api/client";
import { KnowledgeAnswer } from "./KnowledgeAnswer";
import { readKnowledgeEvents } from "../../api/knowledge";

test("shows actual hybrid routing, fallback, separate context counts and derived Wiki provenance", async () => {
  const api = new ApiClient();
  vi.spyOn(api, "knowledgeTask").mockResolvedValue({ status: "COMPLETED", answer: "answer", citations: [], evidence: [], fixed_scope: [], requested_mode: "hybrid", actual_mode: "rag", fallback_reason: "WIKI_UNAVAILABLE", audit: { original_retrieved: 5, wiki_retrieved: 2, linked_original_retrieved: 3, original_sent: 4, wiki_sent: 1, original_bytes: 800, wiki_bytes: 200, context_bytes: 1000 }, wiki_navigation: [{ page_id: "page", title: "Method overview", statements: ["Derived navigation only"], ai_generated: true, human_reviewed: false, independent_study: false }] } as never);
  vi.spyOn(api, "knowledgeEvents").mockImplementation(async function* () {});
  render(<KnowledgeAnswer api={api} conversationId="mode-chat" turnId="turn" />);
  await screen.findByText(/实际模式：原文 RAG/);
  expect(screen.getByText(/WIKI_UNAVAILABLE/)).toBeTruthy();
  expect(screen.getByText(/原文 4 条.*Wiki 1 页/)).toBeTruthy();
  expect(screen.getByText(/不算独立研究/)).toBeTruthy();
  expect(screen.getByText("Method overview")).toBeTruthy();
});

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

test("a delayed source preview cannot enter a newly selected conversation", async () => {
  const api = new ApiClient();
  const ref = { chunk_id: "chunk", document_id: "doc", page: 1 };
  vi.spyOn(api, "knowledgeTask").mockImplementation(async (conversation) => ({ status: "COMPLETED", answer: conversation, citations: conversation === "old-chat" ? [ref] : [], evidence: [{ reference: ref, chunk: { id: "chunk", kind: "text", text: "source", section: [] } }], fixed_scope: [] } as never));
  vi.spyOn(api, "knowledgeEvents").mockImplementation(async function* () {});
  let finish!: (value: never) => void;
  vi.spyOn(api, "evidencePreview").mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  const view = render(<KnowledgeAnswer api={api} conversationId="old-chat" turnId="turn" />);
  fireEvent.click(await screen.findByRole("button", { name: /打开 PDF 第/ }));
  view.rerender(<KnowledgeAnswer api={api} conversationId="new-chat" turnId="new-turn" />);
  await screen.findByText("new-chat");
  finish({ page: 1, warnings: [], element: { text: "old source" } } as never);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(screen.queryByText("old-chat")).toBeNull();
});
