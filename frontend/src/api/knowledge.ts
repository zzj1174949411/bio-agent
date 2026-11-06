import type { ModelDiagnostic } from "./types";
export type KnowledgeBase = { id: string; name: string };
export type KnowledgeUploadLimits = { max_pdf_bytes: number; max_files_per_request: number; max_files_per_selection: number; max_request_bytes: number };
export type KnowledgeJob = { id: string; status: string; stage?: string; progress: number; error_code: string | null };
export type KnowledgeDocument = { id: string; base_id: string; filename: string; status: string; published_revision: string | null; index_revision: string | null; job: KnowledgeJob; warnings: string[] };
export type IndexState = { index_revision: string | null; latest_job: KnowledgeJob | null };
export type KnowledgeReady = { ready: boolean; code: string; prepare_command?: string | null };
export type EvidenceRef = { chunk_id: string; document_id: string; base_id: string; parse_revision: string; index_revision: string; element_id: string; page: number; content_sha256: string };
export type EvidenceHit = { reference: EvidenceRef; chunk: { id: string; kind: string; text: string; section: string[]; context: string; asset_id: string | null } };
export type KnowledgeMode = "rag" | "wiki" | "hybrid";
export type ContextAudit = { original_retrieved: number; wiki_retrieved: number; linked_original_retrieved: number; original_sent: number; wiki_sent: number; original_bytes: number; wiki_bytes: number; context_bytes: number; sent_chunk_ids?: string[]; sent_page_ids?: string[] };
export type WikiNavigation = { base_id: string; generation: string; page_id: string; title: string; statements: string[]; source_chunk_ids: string[]; ai_generated: boolean; human_reviewed: boolean; independent_study: boolean };
export type KnowledgeTask = { id: string; status: string; error_code: string | null; diagnostic?: ModelDiagnostic | null; answer: string | null; citations: EvidenceRef[]; evidence: EvidenceHit[]; fixed_scope: string[]; snapshot: { model: string; revision: number }; requested_mode?: KnowledgeMode; actual_mode?: KnowledgeMode; fallback_reason?: string | null; audit?: ContextAudit; wiki_navigation?: WikiNavigation[] };
export type KnowledgeEvent = { sequence: number; kind: string; data: { status?: string; count?: number; text?: string; code?: string } };
export type TableCell = { text: string; start_row_offset_idx: number; start_col_offset_idx: number; row_span: number; col_span: number; column_header?: boolean; row_header?: boolean };
export type EvidencePreview = { page: number; warnings: string[]; element: { kind: string; text: string; ocr_text: string; captions: string[]; footnotes: string[]; table: { num_rows: number; num_cols: number; table_cells: TableCell[] } | null } };

export const knowledgeTurnPath = (conversation: string, turn: string) => `/workbench/conversations/${encodeURIComponent(conversation)}/turns/${encodeURIComponent(turn)}`;

// Sequence belongs to one task. Reconnect to the same turn only, never a newly selected conversation.
export async function* readKnowledgeEvents(url: string, signal: AbortSignal): AsyncGenerator<KnowledgeEvent> {
  let after = 0;
  let delay = 250;
  while (!signal.aborted) {
    try {
      const response = await fetch(`${url}?after=${after}`, { signal });
      if (!response.ok || !response.body) throw new Error("知识事件连接失败");
      const reader = response.body.getReader();
      const decoder = new TextDecoder(); let buffer = "";
      while (!signal.aborted) {
        const part = await reader.read(); if (part.done) break;
        buffer += decoder.decode(part.value, { stream: true });
        const blocks = buffer.split("\n\n"); buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const raw = block.match(/^data: (.+)$/m)?.[1]; if (!raw) continue;
          const event = JSON.parse(raw) as KnowledgeEvent;
          if (event.sequence <= after) continue;
          after = event.sequence; delay = 250; yield event;
          if (["completed", "failed", "cancelled"].includes(event.kind)) return;
        }
      }
    } catch { if (signal.aborted) return; }
    await new Promise<void>((resolve) => { const timer = setTimeout(resolve, delay); signal.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true }); });
    delay = Math.min(delay * 2, 5000);
  }
}
