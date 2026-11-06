import { useEffect, useMemo, useRef, useState } from "react";
import { ApiClient } from "./api/client";
import type { Artifact, Conversation, DatasetOption, GeoImportState, GeoSearchState, GeoSelection, GeoSourceState, McpServer, Message, ModelProfile, Project, RunSummary, SkillRecord, ToolApprovalRequest, ToolDescriptor, Turn } from "./api/types";
import { Composer } from "./features/chat/Composer";
import { ClarificationCard } from "./features/chat/ClarificationCard";
import { ChatTimeline } from "./features/chat/ChatTimeline";
import { ProjectSidebar } from "./features/projects/ProjectSidebar";
import { ModelSettings } from "./features/models/ModelSettings";
import { ResourcePanel } from "./components/ResourcePanel";
import { ApprovalCard } from "./features/analysis/ApprovalCard";
import { SkillSettings, type SkillView } from "./features/extensions/SkillSettings";
import { McpSettings, type McpDraft } from "./features/extensions/McpSettings";

import { KnowledgeManager } from "./features/knowledge/KnowledgeManager";
import type { KnowledgeBase } from "./api/knowledge";

const turnFailure = (code?: string | null) => code === "MODEL_AUTH_FAILED" ? "运行失败：MODEL_AUTH_FAILED（API Key 无效、未保存或无权访问该模型）" : `运行失败：${code || "UNKNOWN_ERROR"}`;

export function App({ api: suppliedApi }: { api?: ApiClient }) {
  const defaultApi = useMemo(() => new ApiClient(), []); const api = suppliedApi ?? defaultApi;
  const [projects, setProjects] = useState<Project[]>([]); const [activeProjectId, setActiveProjectId] = useState(""); const [conversations, setConversations] = useState<Conversation[]>([]); const [messages, setMessages] = useState<Message[]>([]); const [selected, setSelected] = useState<Conversation | null>(null); const [activeTurn, setActiveTurn] = useState<Turn | null>(null); const activeTurnRef = useRef<Turn | null>(null); const latestTerminalSeqRef = useRef(0); const [approvalRevision, setApprovalRevision] = useState<number | null>(null); const [profiles, setProfiles] = useState<ModelProfile[]>([]); const selectedProfileId = selected?.selected_profile_id ?? ""; const [datasets, setDatasets] = useState<DatasetOption[]>([]); const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([]); const [run, setRun] = useState<RunSummary | null>(null); const [artifacts, setArtifacts] = useState<Artifact[]>([]); const [geoSearch, setGeoSearch] = useState<GeoSearchState | null>(null); const [geoSource, setGeoSource] = useState<GeoSourceState | null>(null); const [geoImport, setGeoImport] = useState<GeoImportState | null>(null); const [confirmedUnknown, setConfirmedUnknown] = useState(false); const [error, setError] = useState(""); const [skillRoot, setSkillRoot] = useState(""); const [skills, setSkills] = useState<SkillView[]>([]); const [skillErrors, setSkillErrors] = useState<Array<{ relative_path: string; code: string }>>([]); const [mcpServers, setMcpServers] = useState<McpServer[]>([]); const [tools, setTools] = useState<ToolDescriptor[]>([]); const [showExtensions, setShowExtensions] = useState(false); const [editingProfileId, setEditingProfileId] = useState(""); const [extensionTab, setExtensionTab] = useState<"models" | "skills" | "mcp">("models"); const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false); const [toolApproval, setToolApproval] = useState<ToolApprovalRequest | null>(null);
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [knowledgeSaving, setKnowledgeSaving] = useState(false); const selectedChatRef = useRef<string | undefined>(undefined); selectedChatRef.current = selected?.id;
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const refreshKnowledge = () => { void api.knowledgeBases().then((result) => setKnowledgeBases(result.items)).catch(() => undefined); };
  useEffect(() => { refreshKnowledge(); }, [api]);
  useEffect(() => { if (!selected) return; localStorage.setItem("bioagent.workbench.chat", JSON.stringify({ project: selected.project_id, chat: selected.id })); }, [selected?.id]);
  useEffect(() => { if (!activeProjectId) return; let live = true; void api.conversations(activeProjectId).then((result) => { if (!live) return; setConversations(result.items); try { const saved = JSON.parse(localStorage.getItem("bioagent.workbench.chat") ?? "null") as { project: string; chat: string } | null; if (saved?.project === activeProjectId) setSelected((current) => current ?? result.items.find((chat) => chat.id === saved.chat) ?? null); } catch { /* Invalid local preference is ignored. */ } }).catch(() => undefined); return () => { live = false; }; }, [api, activeProjectId]);
  const chooseKnowledge = (ids: string[]) => { if (!selected || knowledgeSaving) return; const identity = selected.id; const previous = selected.selected_knowledge_base_ids ?? []; setKnowledgeSaving(true); setSelected((current) => current?.id === identity ? { ...current, selected_knowledge_base_ids: ids } : current); void api.updateConversation(identity, { selected_knowledge_base_ids: ids }).then((conversation) => { setSelected((current) => current?.id === identity ? { ...current, selected_knowledge_base_ids: conversation.selected_knowledge_base_ids } : current); setConversations((items) => items.map((item) => item.id === identity ? { ...item, selected_knowledge_base_ids: conversation.selected_knowledge_base_ids } : item)); }).catch(() => { setSelected((current) => current?.id === identity ? { ...current, selected_knowledge_base_ids: previous } : current); setError("知识库选择保存失败，请重试。"); }).finally(() => setKnowledgeSaving(false)); };
  const refreshProjects = () => void api.projects().then((result) => { setProjects(result.items); setActiveProjectId((current) => result.items.some((project) => project.id === current) ? current : result.items.find((item) => { try { return item.id === JSON.parse(localStorage.getItem("bioagent.workbench.chat") ?? "null")?.project; } catch { return false; } })?.id ?? result.items[0]?.id ?? ""); }).catch(() => setError("无法读取项目列表。"));
  useEffect(() => { void (async () => { try { await api.bootstrap(); refreshProjects(); setProfiles((await api.profiles()).items); } catch { setError("后端尚未连接，请检查本地 API。 "); } })(); }, [api]);
  const refreshExtensions = () => void (async () => { try { const [root, records, servers, directory] = await Promise.all([api.skillRoot(), api.skills(), api.mcpServers(), api.tools()]); const details = await Promise.all(records.items.map((record) => api.skill(record.id).catch(() => ({ record })))); setSkillRoot(root.root); setSkills(details.map((detail) => ({ ...detail.record, preview: "snapshot" in detail ? detail.snapshot?.content : undefined, references: "snapshot" in detail ? detail.snapshot?.references : undefined }))); setMcpServers(servers.items); setTools(directory.items); } catch { setError("无法读取扩展设置。"); } })();
  useEffect(() => { refreshExtensions(); }, [api]);
  useEffect(() => { const pending = activeTurn?.pending_tool_call; if (!pending || typeof pending.approval_id !== "string" || typeof pending.qualified_name !== "string" || typeof pending.capability_revision !== "string" || typeof pending.arguments_hash !== "string") { setToolApproval(null); return; } const tool = tools.find((item) => item.qualified_name === pending.qualified_name); const server = mcpServers.find((item) => item.id === tool?.server_id); const target = server?.http?.endpoint ?? (server?.stdio ? `${server.stdio.executable} ${server.stdio.argv.join(" ")}` : "已保存的 MCP 服务"); setToolApproval({ id: pending.approval_id, callId: typeof pending.call_id === "string" ? pending.call_id : undefined, tool: pending.qualified_name, target, arguments: {}, capabilityRevision: pending.capability_revision, currentCapabilityRevision: tool?.capability_revision, argumentsHash: pending.arguments_hash, expiresAt: typeof pending.expires_at === "string" ? pending.expires_at : "" }); }, [activeTurn, mcpServers, tools]);
  useEffect(() => { setToolApproval((current) => { const currentTool = current && tools.find((tool) => tool.qualified_name === current.tool); return current && currentTool ? { ...current, currentCapabilityRevision: currentTool.capability_revision } : current; }); }, [tools]);
  useEffect(() => { if (!selected) return; let live = true; setMessages([]); setActiveTurn(null); activeTurnRef.current = null; latestTerminalSeqRef.current = 0; setRun(null); setArtifacts([]); setGeoImport(null); setConfirmedUnknown(false); void api.messages(selected.id).then((result) => { if (live) setMessages([...result.items].reverse()); }).catch(() => setError("无法读取对话消息。")); if (selected.geo_search_id) void api.geoSearch(selected.geo_search_id, selected.id).then(setGeoSearch).catch(() => setError("无法恢复 GEO 搜索状态。")); else setGeoSearch(null); if (selected.geo_source_id) void api.geoSource(selected.geo_source_id).then(setGeoSource).catch(() => setError("无法恢复 GEO 来源状态。")); else setGeoSource(null); return () => { live = false; }; }, [api, selected?.id]);
  useEffect(() => { if (!activeTurn?.run_id) { setApprovalRevision(null); setRun(null); setArtifacts([]); return; } void api.runPlan(activeTurn.run_id).then((plan) => setApprovalRevision(plan.plan_revision)).catch(() => setError("无法读取分析计划。")); void api.run(activeTurn.run_id).then((value) => setRun({ status: String(value.status ?? ""), qc_status: typeof value.qc_status === "string" ? value.qc_status : null, report_url: typeof value.report_url === "string" ? value.report_url : null })).catch(() => undefined); void api.artifacts(activeTurn.run_id).then((result) => setArtifacts(result.artifacts.map((item) => ({ name: item.artifact_id, artifact_id: item.artifact_id, sha256: item.sha256, url: api.artifactUrl(activeTurn.run_id as string, item.artifact_id) })))).catch(() => undefined); }, [api, activeTurn?.run_id, activeTurn?.status]);
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    const applySearch = (search: GeoSearchState) => {
      setGeoSearch(search);
      const changes = { geo_search_id: search.id, ...(search.source_id ? { geo_source_id: search.source_id } : {}) };
      setSelected((current) => current?.id === selected.id ? { ...current, ...changes } : current);
      setConversations((current) => current.map((conversation) => conversation.id === selected.id ? { ...conversation, ...changes } : conversation));
      if (search.source_id) void api.geoSource(search.source_id).then(setGeoSource).catch(() => setError("无法读取 GEO 来源。"));
    };
    void (async () => {
      try {
        for await (const event of api.events(selected.id, controller.signal)) {
          if (controller.signal.aborted) return;
          if (event.kind === "message.completed" || event.kind === "message.delta") {
            const text = typeof event.payload.text === "string" ? event.payload.text : "";
            const id = typeof event.payload.message_id === "string" ? event.payload.message_id : `event-${event.seq}`;
            const role = event.payload.role === "user" ? "user" : "assistant";
            setMessages((current) => {
              const existing = current.find((item) => item.id === id);
              if (existing) return current.map((item) => item.id === id ? { ...item, content: event.kind === "message.delta" ? item.content + text : text, partial: event.kind === "message.delta" } : item);
              return [...current, { id, role, turn_id: typeof event.payload.turn_id === "string" ? event.payload.turn_id : undefined, knowledge_ask_id: typeof event.payload.knowledge_ask_id === "string" ? event.payload.knowledge_ask_id : null, content: text, partial: event.kind === "message.delta", dataset_ids: [] }];
            });
          }
          if (event.kind === "run.updated" && typeof event.payload.error_code === "string") setError(`GEO 规划失败：${event.payload.error_code}，请检查模型配置后重新发起规划。`);
          if (event.kind === "geo.source") {
            const sourceId = event.payload.source_id;
            if (typeof sourceId === "string") void api.geoSource(sourceId).then(setGeoSource).catch(() => setError("无法读取 GEO 来源。"));
          }
          if (event.kind === "geo.search.updated" || event.kind === "geo.search.selected") {
            const searchId = event.payload.id;
            if (typeof searchId === "string") void api.geoSearch(searchId, selected.id).then(applySearch).catch(() => setError("无法读取 GEO 搜索结果。"));
          }
          if (event.kind === "geo.updated") {
            const id = event.payload.id;
            const resource = event.payload.resource;
            if (typeof id === "string" && resource === "source") void api.geoSource(id).then(setGeoSource).catch(() => undefined);
            if (typeof id === "string" && resource === "import") void api.geoImport(id).then(setGeoImport).catch(() => undefined);
          }
          if (["input.required", "turn.completed", "turn.failed", "turn.cancelled"].includes(event.kind)) {
            const eventTurnId = typeof event.payload.turn_id === "string" ? event.payload.turn_id : activeTurnRef.current?.id;
            const errorCode = typeof event.payload.error_code === "string" ? event.payload.error_code : null;
            if (event.kind === "turn.failed") setError(turnFailure(errorCode));
            if (event.kind === "turn.completed") setError("");
            if (eventTurnId) {
              latestTerminalSeqRef.current = event.seq;
              const terminalSeq = event.seq;
              const terminalStatus = event.kind === "turn.completed" ? "COMPLETED" : event.kind === "turn.failed" ? "FAILED" : event.kind === "turn.cancelled" ? "CANCELLED" : null;
              if (terminalStatus) {
                const current = activeTurnRef.current;
                const projected: Turn = current?.id === eventTurnId ? { ...current, status: terminalStatus, error_code: errorCode } : { id: eventTurnId, status: terminalStatus, run_id: null, error_code: errorCode, input_revision: 0, pending_input: null };
                activeTurnRef.current = projected;
                setActiveTurn(projected);
              }
              void api.turn(eventTurnId).then((turn) => {
                if (controller.signal.aborted || latestTerminalSeqRef.current !== terminalSeq) return;
                activeTurnRef.current = turn;
                setActiveTurn(turn);
                if (turn.status === "FAILED") setError(turnFailure(turn.error_code));
              }).catch(() => undefined);
            }
          }
        }
      } catch {
        if (!controller.signal.aborted) setError("事件连接已断开，请稍后重试。");
      }
    })();
    return () => controller.abort();
  }, [api, selected?.id]);
  const chooseProject = (project: Project) => { setActiveProjectId(project.id); setSelected(null); setMessages([]); setMobileSidebarOpen(false); void api.conversations(project.id).then((result) => setConversations(result.items)).catch(() => setError("无法读取项目对话。")); };
  const createProject = (title: string) => void api.createProject(title).then((project) => { setProjects((items) => [...items, project]); setActiveProjectId(project.id); setConversations([]); setSelected(null); setMobileSidebarOpen(false); }).catch(() => setError("创建项目失败。"));
  const renameProject = (id: string, title: string) => void api.updateProject(id, { title }).then(refreshProjects).catch(() => setError("重命名项目失败。"));
  const archiveProject = (id: string) => void api.updateProject(id, { archived: true }).then(refreshProjects).catch(() => setError("归档项目失败。"));
  const createConversation = (projectId: string, title: string) => void api.createConversation(projectId, title).then((conversation) => { setConversations((items) => [...items, conversation]); setSelected(conversation); }).catch(() => setError("创建对话失败。"));
  const renameConversation = (id: string, title: string) => void api.updateConversation(id, { title }).then((conversation) => setConversations((items) => items.map((item) => item.id === id ? conversation : item))).catch(() => setError("重命名对话失败。"));
  const archiveConversation = (id: string) => void api.updateConversation(id, { archived: true }).then((conversation) => setConversations((items) => items.map((item) => item.id === id ? conversation : item))).catch(() => setError("归档对话失败。"));
  const chooseModel = (id: string) => {
    if (!selected) return;
    const conversationId = selected.id;
    void api.updateConversation(conversationId, { selected_profile_id: id || null }).then((conversation) => {
      setSelected((current) => current?.id === conversationId ? { ...current, selected_profile_id: conversation.selected_profile_id } : current);
      setConversations((items) => items.map((item) => item.id === conversationId ? { ...item, selected_profile_id: conversation.selected_profile_id } : item));

    }).catch(() => setError("模型选择保存失败，请重试。"));
  };
  const send = (text: string) => { if (!selected) { setError("请先选择一个对话。"); return; } if (!profiles.some((profile) => profile.id === selectedProfileId)) { setError("请选择已保存的模型，或进入设置添加配置。"); return; } setError(""); const submittedChat = selected.id; void api.submitTurn(submittedChat, text, selectedDatasetIds, selectedProfileId || undefined).then((turn) => { if (selectedChatRef.current !== submittedChat) return; const current = activeTurnRef.current; if (current?.id === turn.id && ["COMPLETED", "FAILED", "CANCELLED"].includes(current.status)) return; activeTurnRef.current = turn; setActiveTurn(turn); }).catch(() => setError("消息提交失败。")); };
  const stop = () => { if (!activeTurn) return; void api.cancelTurn(activeTurn.id).then((turn) => { activeTurnRef.current = turn; setActiveTurn(turn); }).catch(() => setError("停止请求失败。")); };
  const approve = (revision: number) => { if (!activeTurn?.run_id) return; void api.approveRun(activeTurn.run_id, revision).then(() => { const approved = { ...activeTurn, status: "RUNNING" }; activeTurnRef.current = approved; setActiveTurn(approved); void api.run(approved.run_id as string).then((value) => setRun({ status: String(value.status ?? ""), qc_status: typeof value.qc_status === "string" ? value.qc_status : null, report_url: typeof value.report_url === "string" ? value.report_url : null })).catch(() => undefined); void api.artifacts(approved.run_id as string).then((result) => setArtifacts(result.artifacts.map((item) => ({ name: item.artifact_id, artifact_id: item.artifact_id, sha256: item.sha256, url: api.artifactUrl(approved.run_id as string, item.artifact_id) })))).catch(() => undefined); }).catch(() => setError("批准分析失败。")); };
  const respond = (requestId: string, revision: number, value: string) => { if (!activeTurn) return; void api.respondToTurn(activeTurn.id, requestId, revision, value).then((turn) => { activeTurnRef.current = turn; setActiveTurn(turn); }).catch(() => setError("澄清响应失败，可能已过期，请刷新后重试。")); };
  const upload = (counts: File, metadata: File) => void api.uploadDataset(counts, metadata).then(({ dataset_id }) => setDatasets((items) => [...items, { id: dataset_id, label: `${counts.name} / ${metadata.name}` }])).catch(() => setError("数据集上传失败。"));
  const selectGeoSearchResult = (accession: string, revision: number) => { if (!geoSearch || !selected) return; void api.selectGeoSearchResult(geoSearch.id, accession, revision, selected.id).then((search) => { setGeoSearch(search); if (search.source_id) void api.geoSource(search.source_id).then(setGeoSource).catch(() => setError("无法读取 GEO 来源。")); }).catch(() => setError("GEO 候选选择失败，可能已过期，请刷新后重试。")); };
  const nextGeoSearchPage = (pageToken: string, revision: number) => { if (!geoSearch || !selected) return; void api.nextGeoSearchPage(geoSearch.id, pageToken, revision, selected.id).then(setGeoSearch).catch(() => setError("GEO 搜索分页失败，可能已过期，请刷新后重试。")); };
  const cancelGeoSearch = () => { if (!geoSearch || !selected) return; void api.cancelGeoSearch(geoSearch.id, selected.id).then(setGeoSearch).catch(() => setError("取消 GEO 搜索失败。")); };
  const retryGeoSearch = () => { if (!activeTurn?.pending_input) { setError("请发送新的 GEO 搜索请求。 "); return; } respond(activeTurn.pending_input.request_id, activeTurn.pending_input.revision, "请重试刚才的 GEO 搜索。"); };
  const confirmGeoCandidate = (candidateId: string, unknown: boolean) => { if (!geoSource) return; setConfirmedUnknown(unknown); void api.createGeoImport(geoSource.id, candidateId, geoSource.revision).then(setGeoImport).catch((reason: unknown) => setError(reason instanceof Error ? `GEO 下载无法开始：${reason.message}` : "GEO 下载无法开始。")); };
  const submitGeoSelection = (selection: GeoSelection) => { if (!geoImport) return; void api.submitGeoSelection(geoImport.id, selection).then(setGeoImport).catch((reason: unknown) => setError(reason instanceof Error ? `样本映射未保存：${reason.message}` : "样本映射未保存。")); };
  const cancelGeoImport = () => { if (!geoImport) return; void api.cancelGeoImport(geoImport.id).then(setGeoImport).catch(() => setError("取消 GEO 下载失败。")); };
  const backToGeoCandidates = () => { if (!geoImport) return; void api.cancelGeoImport(geoImport.id).then(setGeoImport).catch(() => setError("无法返回候选文件。")); };
  const persistModel = async (payload: { label: string; provider: string; model: string; baseUrl: string; apiKey: string }, id?: string, revision?: number) => {
    const configuration = { label: payload.label, provider: payload.provider, model: payload.model, base_url: payload.baseUrl, structured_method: "function_calling", thinking: "default" };
    let createdId = id;
    try {
      const profile = id && revision ? await api.updateProfile(id, revision, configuration) : await api.saveProfile(configuration);
      createdId = profile.id;
      const saved = payload.apiKey && payload.provider !== "ollama" ? await api.saveCredential(profile.id, payload.apiKey) : profile;
      setProfiles((items) => [...items.filter((item) => item.id !== saved.id), saved]);
      setEditingProfileId(saved.id);
      setError("模型配置已保存，请在聊天输入区选择使用。 ");
    } catch {
      try { setProfiles((await api.profiles()).items); if (createdId) setEditingProfileId(createdId); } catch { /* Preserve existing state if backend is offline. */ }
      throw new Error("配置或凭据保存失败，请检查后端连接及系统凭据库后重试。部分配置可能已保存，请确认凭据状态。");
    }
  };
  const saveModel = (payload: { label: string; provider: string; model: string; baseUrl: string; apiKey: string }) => persistModel(payload);
  const updateModel = (id: string, revision: number, payload: { label: string; provider: string; model: string; baseUrl: string; apiKey: string }) => persistModel(payload, id, revision);
  const saveMcp = async (draft: McpDraft) => { try { const payload = { label: draft.label, transport: draft.transport, ...(draft.transport === "stdio" ? { stdio: { executable: draft.executable, argv: draft.argv, cwd: draft.cwd, env_refs: draft.credentialRef ? { MCP_CREDENTIAL: draft.credentialRef } : {} } } : { http: { endpoint: draft.endpoint, header_refs: draft.credentialRef ? { Authorization: draft.credentialRef } : {} } }) }; const server = draft.serverId && draft.revision !== undefined ? await api.updateMcpServer(draft.serverId, draft.revision, payload) : await api.createMcpServer(payload); if (draft.credentialValue) await api.setMcpCredential(server.id, draft.credentialRef, draft.credentialValue); refreshExtensions(); } catch { setError("MCP 服务保存失败。"); } };
  const decideTool = (_approvalId: string, decision: "approve" | "deny", _capabilityRevision: string, _argumentsHash: string) => { if (!activeTurn || !activeTurn.pending_input) return; void api.respondToTurn(activeTurn.id, activeTurn.pending_input.request_id, activeTurn.pending_input.revision, decision).then((turn) => { activeTurnRef.current = turn; setActiveTurn(turn); setToolApproval(null); }).catch(() => setError("工具批准已过期或能力已变化。")); };
  const rescanSkills = () => void api.rescanSkills().then((result) => { setSkills((current) => result.items.map((record) => ({ ...record, changed: current.some((skill) => skill.id === record.id && skill.sha256 !== record.sha256) }))); setSkillErrors(result.errors); if (result.errors.length) setError("Skills 扫描发现校验错误。"); }).catch(() => setError("Skills 扫描失败。"));
  const activeProject = useMemo(() => projects.find((project) => project.id === activeProjectId), [activeProjectId, projects]); const currentPending = activeTurn?.pending_input; const isToolPending = Boolean(currentPending?.question.startsWith("TOOL_APPROVAL:")); const canStop = Boolean(activeTurn && ["QUEUED", "RUNNING", "WAITING_USER"].includes(activeTurn.status));
  return <div className="app-shell"><ProjectSidebar projects={projects} activeProjectId={activeProjectId} conversations={conversations} mobileOpen={mobileSidebarOpen} onMobileClose={() => setMobileSidebarOpen(false)} onProject={chooseProject} onConversation={(conversation) => { setMessages([]); setSelected(conversation); setMobileSidebarOpen(false); }} onCreateProject={createProject} onRenameProject={renameProject} onArchiveProject={archiveProject} onCreateConversation={createConversation} onRenameConversation={renameConversation} onArchiveConversation={archiveConversation} /><main className="conversation"><header><span>{selected?.title ?? activeProject?.title ?? "本地工作台"}</span><div><button className="mobile-sidebar-toggle" type="button" aria-expanded={mobileSidebarOpen} onClick={() => setMobileSidebarOpen((open) => !open)}>项目与对话</button>{canStop && <button type="button" onClick={stop}>停止</button>}<button type="button" onClick={() => { setShowKnowledge(false); setShowExtensions((open) => !open); }}>设置</button><button type="button" onClick={() => { setShowExtensions(false); setShowKnowledge((open) => !open); refreshKnowledge(); }}>知识库</button><button type="button" onClick={() => setError("")}>清除提示</button></div></header>{error && <p className="error" role="alert">{error}</p>}{activeTurn && ["QUEUED", "RUNNING"].includes(activeTurn.status) && <p className="turn-status" role="status">{activeTurn.status === "QUEUED" ? "已提交，等待 Agent 处理…" : "Agent 正在处理请求并检查可用工具…"}</p>}<div className="chat-content" hidden={showExtensions || showKnowledge}><ChatTimeline api={api} conversationId={selected?.id} messages={messages} geo={{ search: geoSearch, source: geoSource, imported: geoImport, onSearchSelect: selectGeoSearchResult, onSearchNext: nextGeoSearchPage, onSearchCancel: cancelGeoSearch, onSearchRetry: retryGeoSearch, onConfirm: confirmGeoCandidate, onCancel: cancelGeoImport, onSelection: submitGeoSelection, onBack: backToGeoCandidates, confirmedUnknown }} toolApproval={toolApproval} onToolDecision={decideTool} />{currentPending && !isToolPending && <ClarificationCard requestId={currentPending.request_id} revision={currentPending.revision} question={currentPending.question} onRespond={respond} />}{activeTurn?.run_id && activeTurn.status === "WAITING_USER" && approvalRevision !== null && <ApprovalCard revision={approvalRevision} onApprove={approve} onReject={stop} />}<fieldset className="knowledge-selection"><legend>对话知识库</legend>{knowledgeBases.map((base) => <label key={base.id}><input type="checkbox" aria-label={`知识库 ${base.name}`} checked={(selected?.selected_knowledge_base_ids ?? []).includes(base.id)} disabled={!selected || canStop || knowledgeSaving} onChange={(event) => chooseKnowledge(event.target.checked ? [...(selected?.selected_knowledge_base_ids ?? []), base.id] : (selected?.selected_knowledge_base_ids ?? []).filter((id) => id !== base.id))} />{base.name}</label>)}{(selected?.selected_knowledge_base_ids ?? []).some((id) => !knowledgeBases.some((base) => base.id === id)) && <span>已选库已删除，请清除选择。</span>}<button disabled={!selected || canStop || knowledgeSaving || !(selected.selected_knowledge_base_ids ?? []).length} onClick={() => chooseKnowledge([])}>清除知识库选择</button><small>仅文献问题使用所选库；GEO 搜索与分析规划照常可用。</small></fieldset><Composer disabled={knowledgeSaving} onSend={send} sending={Boolean(activeTurn && ["QUEUED", "RUNNING"].includes(activeTurn.status))} datasets={datasets} selectedDatasetIds={selectedDatasetIds} onDatasetChange={setSelectedDatasetIds} profiles={profiles.map((profile) => ({ id: profile.id, label: profile.label }))} selectedProfileId={selectedProfileId} onProfileChange={chooseModel} onOpenSettings={() => { setExtensionTab("models"); setShowExtensions(true); }} onUpload={upload} /></div></main><div className="right-column" hidden={showExtensions || showKnowledge}><ResourcePanel run={run} artifacts={artifacts} /></div>{showKnowledge && <div className="settings-view"><KnowledgeManager api={api} onChanged={refreshKnowledge} onClose={() => { setShowKnowledge(false); refreshKnowledge(); }} /></div>}{showExtensions && <section className="settings-view" aria-label="设置"><div className="settings-header"><h1>设置</h1><button type="button" onClick={() => setShowExtensions(false)}>返回聊天</button></div><div className="extension-tabs" role="tablist" aria-label="设置分类"><button type="button" role="tab" aria-selected={extensionTab === "models"} onClick={() => setExtensionTab("models")}>模型与 API</button><button type="button" role="tab" aria-selected={extensionTab === "skills"} onClick={() => setExtensionTab("skills")}>Skills</button><button type="button" role="tab" aria-selected={extensionTab === "mcp"} onClick={() => setExtensionTab("mcp")}>MCP</button></div>{extensionTab === "models" ? <ModelSettings onSave={saveModel} profiles={profiles} selectedProfileId={editingProfileId} onSelectProfile={setEditingProfileId} onUpdate={updateModel} onDelete={(id, revision) => api.deleteProfile(id, revision).then(() => { setProfiles((items) => items.filter((item) => item.id !== id)); setEditingProfileId(""); }).catch(() => { throw new Error("删除模型失败，请重试。"); })} onClearCredential={(id) => api.clearCredential(id).then((profile) => setProfiles((items) => items.map((item) => item.id === id ? profile : item))).catch(() => { throw new Error("清除凭据失败，请重试。"); })} onProbe={(id) => api.probeProfile(id).then((result) => { if (!result.ok) throw new Error(turnFailure(result.code)); setError("连接及结构化输出探测成功；尚未验证全部工具能力。"); })} /> : extensionTab === "skills" ? <SkillSettings root={skillRoot} skills={skills} errors={skillErrors} onRescan={rescanSkills} onSetRoot={(root) => void api.setSkillRoot(root).then((result) => setSkillRoot(result.root)).catch(() => setError("Skill 根目录保存失败。"))} onSetEnabled={(skill, enabled) => void api.setSkillEnabled(skill.id, enabled, skill.sha256).then(refreshExtensions).catch(() => setError("Skill 状态更新失败。"))} /> : <McpSettings servers={mcpServers} tools={tools} onSave={saveMcp} onConnect={(id) => void api.connectMcpServer(id).then((connection) => { setMcpServers((items) => items.map((server) => server.id === id ? { ...server, protocol_version: connection.protocol_version ?? null } : server)); void api.tools().then((directory) => setTools(directory.items)); }).catch(() => setError("MCP 连接失败。"))} onDisconnect={(id) => void api.disconnectMcpServer(id).then(() => setMcpServers((items) => items.map((server) => server.id === id ? { ...server, protocol_version: null } : server))).catch(() => setError("MCP 断开失败。"))} onPolicyChange={(tool, policy) => void api.setToolPolicy(tool.qualified_name, policy, tool.capability_revision).then(refreshExtensions).catch(() => setError("工具权限更新失败。"))} />}</section>}</div>;
}
