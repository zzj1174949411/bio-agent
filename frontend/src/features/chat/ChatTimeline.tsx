import type { GeoImportState, GeoSearchState, GeoSelection, GeoSourceState, Message, ToolApprovalRequest } from "../../api/types";
import { SafeMarkdown } from "../../components/SafeMarkdown";
import { ToolApprovalCard } from "../extensions/ToolApprovalCard";
import { GeoImportProgress } from "../geo/GeoImportProgress";
import { GeoSearchResults } from "../geo/GeoSearchResults";
import { GeoSourceCard } from "../geo/GeoSourceCard";
import { SampleMapping } from "../geo/SampleMapping";
import { ApiClient } from "../../api/client";
import { KnowledgeAnswer } from "../knowledge/KnowledgeAnswer";

type GeoWorkbench = { search: GeoSearchState | null; source: GeoSourceState | null; imported: GeoImportState | null; onSearchSelect: (accession: string, revision: number) => void; onSearchNext: (pageToken: string, revision: number) => void; onSearchCancel: () => void; onSearchRetry: () => void; onConfirm: (candidateId: string, confirmedUnknown: boolean) => void; onCancel: () => void; onSelection: (selection: GeoSelection) => void; onBack: () => void; confirmedUnknown: boolean };

export function ChatTimeline({ messages, geo, toolApproval, onToolDecision, api, conversationId }: { messages: Message[]; geo?: GeoWorkbench; toolApproval?: ToolApprovalRequest | null; onToolDecision?: (id: string, decision: "approve" | "deny", capabilityRevision: string, argumentsHash: string) => void; api?: ApiClient; conversationId?: string }) {
  const source = geo?.source?.source;
  const imported = geo?.imported;
  const selectedCandidate = source?.candidates.find((candidate) => candidate.id === imported?.candidate_id);
  return <div className="timeline" aria-live="polite">{messages.length === 0 ? <p className="empty">开始一段可审计的分析对话</p> : messages.map((message) => <article className={`message ${message.role}`} key={message.id}><small>{message.role === "user" ? "你" : "Bio-Agent"}</small><SafeMarkdown source={message.content} />{message.knowledge_ask_id && message.turn_id && api && conversationId && <KnowledgeAnswer api={api} conversationId={conversationId} turnId={message.turn_id} />}{message.partial && <span className="partial">生成中…</span>}</article>)}{toolApproval && onToolDecision && <ToolApprovalCard request={toolApproval} onDecide={onToolDecision} />}{geo?.search && <GeoSearchResults search={geo.search} onSelect={geo.onSearchSelect} onNext={geo.onSearchNext} onCancel={geo.onSearchCancel} onRetry={geo.onSearchRetry} />}{geo?.source && geo.source.status === "AWAITING_SELECTION" && (!imported || ["CANCELLED", "FAILED"].includes(imported.status)) && <GeoSourceCard accession={source?.accession ?? geo.source.accession} title={source?.title} organisms={source?.organisms} platforms={source?.platforms} candidates={source?.candidates ?? []} onConfirm={geo.onConfirm} />}{imported && imported.status !== "AWAITING_MAPPING" && <GeoImportProgress status={imported.status} bytesDownloaded={imported.bytes_downloaded ?? 0} totalBytes={selectedCandidate?.size_bytes ?? null} errorCode={imported.error_code} onCancel={geo.onCancel} />}{source && imported?.status === "AWAITING_MAPPING" && <SampleMapping source={source} imported={imported} errorCode={imported.error_code} confirmedRawType={geo.confirmedUnknown} requiresRawConfirmation={selectedCandidate?.data_kind === "UNKNOWN"} onSubmit={geo.onSelection} onBack={geo.onBack} />}</div>;
}
