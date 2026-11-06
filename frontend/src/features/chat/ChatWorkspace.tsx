import { MatrixImport } from "./MatrixImport";
import { useEffect, useRef, useState } from "react";
import { ApiClient } from "../../api/client";
import type { Conversation, DatasetOption, GeoImportState, GeoSearchState, GeoSelection, GeoSourceState, McpServer, Message, ModelProfile, ToolApprovalRequest, ToolDescriptor, Turn } from "../../api/types";
import type { KnowledgeBase } from "../../api/knowledge";
import { FileButton, FilePreviewProvider, useFilePreview } from "../../components/FilePreview";
import { ApprovalCard } from "../analysis/ApprovalCard";
import { modelFailure } from "../models/errors";
import { ChatTimeline } from "./ChatTimeline";
import { ClarificationCard } from "./ClarificationCard";
import { Composer } from "./Composer";
import { useRun } from "./useRun";

export type ChatDraft = { text: string; counts: File | null; metadata: File | null; datasets: DatasetOption[]; selectedDatasetIds: string[] };
export const emptyDraft = (): ChatDraft => ({ text: "", counts: null, metadata: null, datasets: [], selectedDatasetIds: [] });
type Props = { api: ApiClient; conversation: Conversation; profiles: ModelProfile[]; knowledgeBases: KnowledgeBase[]; draft: ChatDraft; onDraftChange: (draft: ChatDraft) => void; onConversationChange: (chat: Conversation) => void; onOpenSettings: () => void; onOpenKnowledge: () => void; tools?: ToolDescriptor[]; mcpServers?: McpServer[] };
function FilesToggle() { const preview = useFilePreview(); return <button onClick={() => preview?.openList()}>文件</button>; }

// Mounted by conversation ID: every request, stream and preview has one conversation owner.
export function ChatWorkspace({ api, conversation, profiles, knowledgeBases, draft, onDraftChange, onConversationChange, onOpenSettings, onOpenKnowledge, tools = [], mcpServers = [] }: Props) {
  const [showMatrix, setShowMatrix] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]); const [turn, setTurn] = useState<Turn | null>(null); const turnRef = useRef<Turn | null>(null);
  const [geoSearch, setGeoSearch] = useState<GeoSearchState | null>(null); const [geoSource, setGeoSource] = useState<GeoSourceState | null>(null); const [geoImport, setGeoImport] = useState<GeoImportState | null>(null);
  const [unknown, setUnknown] = useState(false); const [error, setError] = useState(""); const [saving, setSaving] = useState(false); const [uploading, setUploading] = useState(false); const [submitting, setSubmitting] = useState(false); const [validation, setValidation] = useState<Record<string, unknown> | null>(null);
  const alive = useRef(true); const requestVersion = useRef(0); const draftRef = useRef(draft); draftRef.current = draft; const updateRef = useRef(onDraftChange); updateRef.current = onDraftChange;
  const conversationRef = useRef(conversation); conversationRef.current = conversation;
  const [runId, setRunId] = useState<string | null>(null); const runRef = useRef<string | null>(null);
  const analysis = useRun(api, runId);
  const patchDraft = (changes: Partial<ChatDraft>) => { const next = { ...draftRef.current, ...changes }; draftRef.current = next; updateRef.current(next); };
  const applyTurn = (next: Turn) => { if (!alive.current) return; turnRef.current = next; setTurn(next); if (next.run_id) { runRef.current = next.run_id; setRunId(next.run_id); } };
  const fetchTurn = async (id: string) => { const version = ++requestVersion.current; try { const next = await api.turn(id); if (alive.current && version === requestVersion.current) applyTurn(next); } catch { if (alive.current) setError("无法恢复当前轮次，请检查连接。"); } };
  const safe = <T,>(promise: Promise<T>, apply: (value: T) => void) => { void promise.then((value) => { if (alive.current) apply(value); }).catch(() => { if (alive.current) setError("无法核验当前对话资源，请检查连接。"); }); };
  const applySearch = (search: GeoSearchState) => { setGeoSearch(search); onConversationChange({ ...conversationRef.current, geo_search_id: search.id, geo_source_id: search.source_id ?? conversationRef.current.geo_source_id }); if (search.source_id) safe(api.geoSource(search.source_id), setGeoSource); };
  useEffect(() => {
    alive.current = true; const controller = new AbortController(); let sequence = 0;
    void api.messages(conversation.id).then((result) => { if (!alive.current) return; setMessages((current) => [...new Map([...result.items.slice().reverse(), ...current].map((message) => [message.id, message])).values()]); const ids = [...new Set(result.items.map((message) => message.turn_id).filter((id): id is string => !!id))];
      if (ids[0] && !turnRef.current) void fetchTurn(ids[0]);
      // Keep the latest analysis visible even when later ordinary turns have no run_id.
      void (async () => { for (const id of ids) { if (!alive.current || runRef.current) break; try { const saved = await api.turn(id); if (!alive.current || runRef.current) break; if (saved.run_id) { runRef.current = saved.run_id; setRunId(saved.run_id); break; } } catch { if (alive.current) setError("无法恢复历史分析文件，请检查连接。"); break; } } })(); }).catch(() => { if (alive.current) setError("无法读取对话消息。"); });
    safe(api.matrixLatest(conversation.id), (value) => { if (value?.id) setShowMatrix(true); });
    if (conversation.geo_search_id) safe(api.geoSearch(conversation.geo_search_id, conversation.id), setGeoSearch);
    if (conversation.geo_source_id) safe(api.geoSource(conversation.geo_source_id), setGeoSource);
    void (async () => { try { for await (const event of api.events(conversation.id, controller.signal)) {
      if (!alive.current || controller.signal.aborted) return; if (event.seq <= sequence) continue; sequence = event.seq;
      const payload = event.payload;
      if (["message.completed", "message.delta"].includes(event.kind)) {
        const id = typeof payload.message_id === "string" ? payload.message_id : `event-${event.seq}`; const text = typeof payload.text === "string" ? payload.text : "";
        setMessages((current) => { const existing = current.find((item) => item.id === id); if (existing) return current.map((item) => item.id === id ? { ...item, content: event.kind === "message.delta" ? item.content + text : text, partial: event.kind === "message.delta" } : item);
          return [...current, { id, role: payload.role === "user" ? "user" : "assistant", content: text, partial: event.kind === "message.delta", dataset_ids: Array.isArray(payload.dataset_ids) ? payload.dataset_ids.filter((item): item is string => typeof item === "string") : [], turn_id: typeof payload.turn_id === "string" ? payload.turn_id : undefined, knowledge_ask_id: typeof payload.knowledge_ask_id === "string" ? payload.knowledge_ask_id : null }]; });
      }
      if (["input.required", "turn.completed", "turn.failed", "turn.cancelled", "run.updated"].includes(event.kind)) {
        if (event.kind === "turn.failed" || typeof payload.error_code === "string") setError(modelFailure(typeof payload.error_code === "string" ? payload.error_code : null));
        const id = typeof payload.turn_id === "string" ? payload.turn_id : turnRef.current?.id;
        if (id) { const status = event.kind === "turn.completed" ? "COMPLETED" : event.kind === "turn.failed" ? "FAILED" : event.kind === "turn.cancelled" ? "CANCELLED" : null;
          if (status) applyTurn({ ...(turnRef.current?.id === id ? turnRef.current : { id, run_id: null, input_revision: 0, pending_input: null }), status });
          void fetchTurn(id);
        }
      }
      if (event.kind === "geo.source" && typeof payload.source_id === "string") safe(api.geoSource(payload.source_id), setGeoSource);
      if (["geo.search.updated", "geo.search.selected"].includes(event.kind) && typeof payload.id === "string") safe(api.geoSearch(payload.id, conversation.id), applySearch);
      if (event.kind === "geo.updated" && typeof payload.id === "string") {
        if (payload.resource === "source") safe(api.geoSource(payload.id), setGeoSource);
        if (payload.resource === "import") safe(api.geoImport(payload.id), setGeoImport);
      }
    } } catch { if (!controller.signal.aborted && alive.current) setError("事件连接已断开，请检查本地 API。"); } })();
    return () => { alive.current = false; requestVersion.current++; controller.abort(); };
  }, [api, conversation.id]);

  const changeConversation = async (changes: Parameters<ApiClient["updateConversation"]>[1]) => { if (saving) return; setSaving(true); onConversationChange({ ...conversation, ...changes }); try { const value = await api.updateConversation(conversation.id, changes); if (alive.current) onConversationChange(value); } catch { if (alive.current) { onConversationChange(conversation); setError("对话配置保存失败，请重试。"); } } finally { if (alive.current) setSaving(false); } };
  const send = async (text: string) => { if (submitting) return; if (!profiles.some((profile) => profile.id === conversation.selected_profile_id)) { setError("请选择已保存的模型，或进入设置添加配置。"); patchDraft({ text }); return; } setSubmitting(true); setError(""); const version = requestVersion.current;
    try { const next = await api.submitTurn(conversation.id, text, draftRef.current.selectedDatasetIds, conversation.selected_profile_id ?? undefined); if (!alive.current) return; if (version === requestVersion.current || turnRef.current?.id !== next.id) applyTurn(next); }
    catch { if (alive.current) { setError("消息提交失败，请检查连接后重试。"); patchDraft({ text }); } } finally { if (alive.current) setSubmitting(false); }
  };
  const stop = () => { if (turn) safe(api.cancelTurn(turn.id), applyTurn); };
  const respond = (requestId: string, revision: number, value: string) => { if (turn) safe(api.respondToTurn(turn.id, requestId, revision, value), applyTurn); };
  const upload = async (counts: File, metadata: File) => { if (uploading) return; setUploading(true); setError(""); try { const result = await api.uploadDataset(counts, metadata); if (!alive.current) return;
    patchDraft({ counts: null, metadata: null, datasets: [...draftRef.current.datasets, { id: result.dataset_id, label: `${counts.name} / ${metadata.name}` }], selectedDatasetIds: [...draftRef.current.selectedDatasetIds, result.dataset_id] });
    safe(api.datasetValidation(result.dataset_id), setValidation);
  } catch { if (alive.current) setError("数据集上传或校验失败，文件保留在本对话待导入区。"); } finally { if (alive.current) setUploading(false); } };
  const searchSelect = (accession: string, revision: number) => { if (geoSearch) safe(api.selectGeoSearchResult(geoSearch.id, accession, revision, conversation.id), applySearch); };
  const searchNext = (token: string, revision: number) => { if (geoSearch) safe(api.nextGeoSearchPage(geoSearch.id, token, revision, conversation.id), setGeoSearch); };
  const searchCancel = () => { if (geoSearch) safe(api.cancelGeoSearch(geoSearch.id, conversation.id), setGeoSearch); };
  const searchRetry = () => { if (turn?.pending_input) respond(turn.pending_input.request_id, turn.pending_input.revision, "请重试刚才的 GEO 搜索。"); else setError("请发送新的 GEO 搜索请求。"); };
  const confirm = (candidate: string, raw: boolean) => { if (geoSource) { setUnknown(raw); safe(api.createGeoImport(geoSource.id, candidate, geoSource.revision), setGeoImport); } };
  const selectGroups = (selection: GeoSelection) => { if (geoImport) safe(api.submitGeoSelection(geoImport.id, selection), setGeoImport); };
  const cancelImport = () => { if (geoImport) safe(api.cancelGeoImport(geoImport.id), setGeoImport); };
  const pending = turn?.pending_input; const isTool = !!pending?.question.startsWith("TOOL_APPROVAL:"); const operationBusy = submitting || !!turn && ["RUNNING", "QUEUED"].includes(turn.status) && (!turn.run_id || !["COMPLETED", "FAILED", "CANCELLED"].includes(analysis.run?.status ?? ""));
  let toolApproval: ToolApprovalRequest | null = null;
  const tool = turn?.pending_tool_call;
  if (tool && typeof tool.approval_id === "string" && typeof tool.qualified_name === "string" && typeof tool.capability_revision === "string" && typeof tool.arguments_hash === "string") {
    const descriptor = tools.find((item) => item.qualified_name === tool.qualified_name); const server = mcpServers.find((item) => item.id === descriptor?.server_id);
    toolApproval = { id: tool.approval_id, tool: tool.qualified_name, target: server?.http?.endpoint ?? (server?.stdio ? `${server.stdio.executable} ${server.stdio.argv.join(" ")}` : "已保存的 MCP 服务"), arguments: {}, capabilityRevision: tool.capability_revision, currentCapabilityRevision: descriptor?.capability_revision, argumentsHash: tool.arguments_hash, expiresAt: typeof tool.expires_at === "string" ? tool.expires_at : "" };
  }
  const decideTool = (_id: string, decision: "approve" | "deny") => { if (pending) respond(pending.request_id, pending.revision, decision); };
  const historyDatasets = messages.flatMap((message) => message.dataset_ids ?? []).map((id) => ({ id, label: `数据集 ${id.slice(0, 8)}` }));
  const datasets = [...new Map([...historyDatasets, ...draft.datasets].map((item) => [item.id, item])).values()];
  const selectedBases = conversation.selected_knowledge_base_ids ?? [];
  const knowledge = <details className="composer-knowledge"><summary>知识库{selectedBases.length ? ` (${selectedBases.length})` : " · 未选择"}</summary><fieldset aria-label="对话知识库"><legend>对话知识库</legend>{knowledgeBases.map((base) => <label key={base.id}><input type="checkbox" aria-label={`知识库 ${base.name}`} checked={selectedBases.includes(base.id)} disabled={saving || operationBusy} onChange={(event) => void changeConversation({ selected_knowledge_base_ids: event.target.checked ? [...selectedBases, base.id] : selectedBases.filter((id) => id !== base.id) })} />{base.name}</label>)}{selectedBases.some((id) => !knowledgeBases.some((base) => base.id === id)) && <p>已选库已删除，请清除选择。</p>}<button disabled={saving || operationBusy || !selectedBases.length} onClick={() => void changeConversation({ selected_knowledge_base_ids: [] })}>清除知识库选择</button><label>知识检索模式<select aria-label="知识检索模式" value={conversation.knowledge_mode ?? "rag"} disabled={saving || operationBusy} onChange={(event) => void changeConversation({ knowledge_mode: event.target.value as "rag" | "hybrid" })}><option value="rag">原文 RAG（默认）</option><option value="hybrid">原文 + Wiki 混合</option></select></label><small>仅文献问题使用所选库；普通对话和 GEO 入口照常可用。</small></fieldset></details>;
  return <FilePreviewProvider api={api} files={analysis.files}><section className="chat-workspace"><header className="chat-heading"><h1>{conversation.title}</h1><div>{operationBusy && !turn?.run_id && <button onClick={stop}>停止</button>}<FilesToggle /></div></header>{(error || analysis.error) && <p role="alert" className="error">{error || analysis.error}</p>}<div className="chat-content"><ChatTimeline api={api} conversationId={conversation.id} messages={messages} geo={{ search: geoSearch, source: geoSource, imported: geoImport, confirmedUnknown: unknown, onSearchSelect: searchSelect, onSearchNext: searchNext, onSearchCancel: searchCancel, onSearchRetry: searchRetry, onConfirm: confirm, onSelection: selectGroups, onCancel: cancelImport, onBack: cancelImport }} toolApproval={toolApproval} onToolDecision={decideTool}>
    {operationBusy && <p className="turn-status" role="status">{turn?.status === "QUEUED" ? "已排队，等待处理…" : "正在处理请求并检查工具…"}</p>}
    {showMatrix && <MatrixImport onQuestion={(text) => patchDraft({ text })} api={api} chat={conversation.id} profile={conversation.selected_profile_id ?? ""} onConfirmed={(value) => { if (value.dataset_id) patchDraft({ datasets: [...draftRef.current.datasets.filter((d) => d.id !== value.dataset_id), { id: value.dataset_id, label: "已确认单矩阵" }], selectedDatasetIds: [value.dataset_id] }); if (value.turn_id) void fetchTurn(value.turn_id); }} />}
    {validation && <details className="card"><summary>本次数据集校验结果</summary><pre>{JSON.stringify(validation, null, 2)}</pre></details>}
    {pending && !isTool && <ClarificationCard requestId={pending.request_id} revision={pending.revision} question={pending.question} onRespond={respond} />}
    {analysis.plan && <ApprovalCard key={`${analysis.plan.run_id}:${analysis.plan.plan_revision}`} revision={analysis.plan.plan_revision} plan={analysis.plan.plan} busy={analysis.busy} onApprove={(revision) => void analysis.approve(revision)} onReject={() => void analysis.cancel()} />}
    {analysis.run && <article className="message assistant run-message"><small>运行与结果</small><p role="status">运行状态：{analysis.run.status}</p>{analysis.run.qc_status && <p>QC: {analysis.run.qc_status}</p>}{["QUEUED", "RUNNING"].includes(analysis.run.status) && <button disabled={analysis.busy} onClick={() => void analysis.cancel()}>停止运行</button>}{analysis.files.map((file) => <div className="result-file" key={file.url}><FileButton file={file} /><a href={file.url} download>下载 {file.name}</a></div>)}</article>}
    </ChatTimeline><Composer value={draft.text} onValueChange={(text) => patchDraft({ text })} counts={draft.counts} metadata={draft.metadata} onFilesChange={(counts, metadata) => patchDraft({ counts, metadata })} onSend={(text) => void send(text)} disabled={saving || uploading} sending={operationBusy} datasets={datasets} selectedDatasetIds={draft.selectedDatasetIds} onDatasetChange={(selectedDatasetIds) => patchDraft({ selectedDatasetIds })} profiles={profiles.map((profile) => ({ id: profile.id, label: profile.label }))} selectedProfileId={conversation.selected_profile_id ?? ""} onProfileChange={(id) => void changeConversation({ selected_profile_id: id || null })} onOpenSettings={onOpenSettings} onOpenMatrix={() => setShowMatrix(true)} onOpenKnowledge={onOpenKnowledge} onUpload={(a, b) => void upload(a, b)} knowledge={knowledge} /></div></section></FilePreviewProvider>;
}
