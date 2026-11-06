import type { GeoImportState, GeoSelection, GeoSourceState, Message, ToolApprovalRequest } from "../../api/types";
import { SafeMarkdown } from "../../components/SafeMarkdown";
import { ToolApprovalCard } from "../extensions/ToolApprovalCard";
import { GeoImportProgress } from "../geo/GeoImportProgress";
import { GeoSourceCard } from "../geo/GeoSourceCard";
import { SampleMapping } from "../geo/SampleMapping";

type GeoWorkbench = { source: GeoSourceState | null; imported: GeoImportState | null; onConfirm: (candidateId: string, confirmedUnknown: boolean) => void; onCancel: () => void; onSelection: (selection: GeoSelection) => void; onBack: () => void; confirmedUnknown: boolean };

export function ChatTimeline({ messages, geo, toolApproval, onToolDecision }: { messages: Message[]; geo?: GeoWorkbench; toolApproval?: ToolApprovalRequest | null; onToolDecision?: (id: string, decision: "approve" | "deny", capabilityRevision: string, argumentsHash: string) => void }) {
  const source = geo?.source?.source;
  const imported = geo?.imported;
  const selectedCandidate = source?.candidates.find((candidate) => candidate.id === imported?.candidate_id);
  return <div className="timeline" aria-live="polite">{messages.length === 0 ? <p className="empty">开始一段可审计的分析对话</p> : messages.map((message) => <article className={`message ${message.role}`} key={message.id}><small>{message.role === "user" ? "你" : "Bio-Agent"}</small><SafeMarkdown source={message.content} />{message.partial && <span className="partial">生成中…</span>}</article>)}{toolApproval && onToolDecision && <ToolApprovalCard request={toolApproval} onDecide={onToolDecision} />}{geo?.source && geo.source.status === "AWAITING_SELECTION" && (!imported || ["CANCELLED", "FAILED"].includes(imported.status)) && <GeoSourceCard accession={source?.accession ?? geo.source.accession} title={source?.title} organisms={source?.organisms} platforms={source?.platforms} candidates={source?.candidates ?? []} onConfirm={geo.onConfirm} />}{imported && imported.status !== "AWAITING_MAPPING" && <GeoImportProgress status={imported.status} bytesDownloaded={imported.bytes_downloaded ?? 0} totalBytes={selectedCandidate?.size_bytes ?? null} errorCode={imported.error_code} onCancel={geo.onCancel} />}{source && imported?.status === "AWAITING_MAPPING" && <SampleMapping source={source} imported={imported} errorCode={imported.error_code} confirmedRawType={geo.confirmedUnknown} requiresRawConfirmation={selectedCandidate?.data_kind === "UNKNOWN"} onSubmit={geo.onSelection} onBack={geo.onBack} />}</div>;
}
