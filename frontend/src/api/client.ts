import type { MatrixDraft } from "../features/chat/MatrixImport";
import type { Conversation, GeoImportState, GeoSearchRequest, GeoSearchState, GeoSelection, GeoSourceState, McpServer, Message, ModelProfile, Project, SkillDetail, SkillRecord, ToolDescriptor, ToolPolicy, Turn } from "./types";
import { parseEventBlock, type WorkbenchEvent } from "./events";
import { wikiPath, type WikiRequest, type WikiPreflight, type WikiList, type WikiPage, type WikiJob } from "./wiki";
import { knowledgeTurnPath, readKnowledgeEvents, type KnowledgeBase, type KnowledgeDocument, type KnowledgeJob, type IndexState, type KnowledgeReady, type KnowledgeTask, type EvidencePreview, type KnowledgeUploadLimits } from "./knowledge";

type ErrorBody = { detail?: { code?: string } };

export class ApiError extends Error {
  constructor(public readonly code: string, public readonly status: number) { super(code); }
}

export class ApiClient {
  private csrf: string | null = null;
  constructor(private readonly base = "/api/v1") {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(this.csrf ? { "X-CSRF-Token": this.csrf } : {}), ...init.headers },
    });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as ErrorBody;
      throw new ApiError(body.detail?.code ?? "REQUEST_FAILED", response.status);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  async bootstrap(): Promise<void> { this.csrf = (await this.request<{ csrf_token: string }>("/workbench/bootstrap")).csrf_token; }
  matrixResults(chat: string, id: string): Promise<Record<string, unknown>> { return this.request(`/workbench/conversations/${chat}/matrices/${id}/results`); }
  matrixLatest(chat: string): Promise<MatrixDraft | null> { return this.request(`/workbench/conversations/${chat}/matrices`); }
  matrixPreview(chat: string, id: string, direction: string): Promise<MatrixDraft> { return this.request(`/workbench/conversations/${chat}/matrices/${id}?direction=${direction}`); }
  matrixConfirm(chat: string, id: string, payload: Record<string, unknown>): Promise<MatrixDraft> { return this.request(`/workbench/conversations/${chat}/matrices/${id}/confirm`, { method: "POST", body: JSON.stringify(payload) }); }
  async matrixUpload(chat: string, file: File): Promise<MatrixDraft> { const form = new FormData(); form.append("file", file); const response = await fetch(`${this.base}/workbench/conversations/${chat}/matrices`, { method: "POST", body: form, headers: this.csrf ? { "X-CSRF-Token": this.csrf } : {} }); if (!response.ok) { const body = await response.json(); throw new Error(body.detail?.code ?? "MATRIX_UPLOAD_FAILED"); } return response.json(); }
  projects(): Promise<{ items: Project[] }> { return this.request("/workbench/projects"); }
  createProject(title: string): Promise<Project> { return this.request("/workbench/projects", { method: "POST", body: JSON.stringify({ title }) }); }
  updateProject(id: string, payload: { title?: string; archived?: boolean }): Promise<Project> { return this.request(`/workbench/projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) }); }
  conversations(projectId: string): Promise<{ items: Conversation[] }> { return this.request(`/workbench/conversations?project_id=${encodeURIComponent(projectId)}`); }
  createConversation(projectId: string, title: string): Promise<Conversation> { return this.request("/workbench/conversations", { method: "POST", body: JSON.stringify({ project_id: projectId, title }) }); }
  updateConversation(id: string, payload: { title?: string; archived?: boolean; selected_profile_id?: string | null; selected_knowledge_base_ids?: string[]; knowledge_mode?: "rag" | "hybrid" }): Promise<Conversation> { return this.request(`/workbench/conversations/${id}`, { method: "PATCH", body: JSON.stringify(payload) }); }
  messages(conversationId: string): Promise<{ items: Message[] }> { return this.request(`/workbench/conversations/${conversationId}/messages`); }
  submitTurn(conversationId: string, text: string, datasetIds: string[] = [], profileId?: string): Promise<Turn> {
    return this.request(`/workbench/conversations/${conversationId}/turns`, { method: "POST", body: JSON.stringify({ client_request_id: crypto.randomUUID(), text, dataset_ids: datasetIds, profile_id: profileId }) });
  }
  turn(turnId: string): Promise<Turn> { return this.request(`/workbench/turns/${turnId}`); }
  cancelTurn(turnId: string): Promise<Turn> { return this.request(`/workbench/turns/${turnId}/cancel`, { method: "POST", body: "{}" }); }
  respondToTurn(turnId: string, requestId: string, revision: number, value: string): Promise<Turn> {
    return this.request(`/workbench/turns/${turnId}/responses`, { method: "POST", body: JSON.stringify({ request_id: requestId, revision, action: "clarify", value }) });
  }
  approveRun(runId: string, planRevision: number): Promise<Record<string, unknown>> {
    return this.request(`/runs/${runId}/approval`, { method: "POST", body: JSON.stringify({ action: "approve", plan_revision: planRevision }) });
  }
  cancelRun(runId: string): Promise<Record<string, unknown>> {
    return this.request(`/runs/${runId}/cancel`, { method: "POST", body: "{}" });
  }
  runPlan(runId: string): Promise<{ run_id: string; plan_revision: number; plan: Record<string, unknown> }> {
    return this.request(`/runs/${runId}/plan`);
  }
  run(runId: string): Promise<Record<string, unknown>> { return this.request(`/runs/${runId}`); }
  artifacts(runId: string): Promise<{ run_id: string; artifacts: Array<{ artifact_id: string; sha256: string; name?: string; media_type?: string }> }> { return this.request(`/runs/${runId}/artifacts`); }
  async readArtifact(url: string, signal: AbortSignal): Promise<{ blob: Blob; type: string }> {
    if (!/^\/api\/v1\/runs\/[\w-]+\/artifacts\/[^/?#]+$/.test(url)) throw new Error("非受控文件地址");
    const response = await fetch(url, { signal });
    if (!response.ok || !response.body) throw new Error("文件不可用或完整性核验失败");
    const limit = 8 * 1024 * 1024;
    if (Number(response.headers.get("content-length")) > limit) { await response.body.cancel(); throw new Error("文件超过 8 MiB 预览上限，请下载核查"); }
    const reader = response.body.getReader(); const parts: Uint8Array<ArrayBuffer>[] = []; let size = 0;
    try { while (true) { const part = await reader.read(); if (part.done) break; size += part.value.byteLength;
      if (size > limit) throw new Error("文件超过 8 MiB 预览上限，请下载核查");
      parts.push(new Uint8Array(part.value));
    } } finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
    const type = response.headers.get("content-type")?.split(";")[0] ?? "application/octet-stream";
    return { blob: new Blob(parts, { type }), type };
  }
  artifactUrl(runId: string, artifactId: string): string { return `${this.base}/runs/${runId}/artifacts/${encodeURIComponent(artifactId)}`; }
  datasetValidation(datasetId: string): Promise<Record<string, unknown>> { return this.request(`/datasets/${encodeURIComponent(datasetId)}/validation`); }
  async uploadDataset(counts: File, metadata: File): Promise<{ dataset_id: string }> {
    const form = new FormData(); form.append("counts", counts); form.append("metadata", metadata);
    const response = await fetch(`${this.base}/datasets`, { method: "POST", body: form, headers: this.csrf ? { "X-CSRF-Token": this.csrf } : {} });
    if (!response.ok) throw new ApiError("DATASET_UPLOAD_FAILED", response.status);
    return (await response.json()) as { dataset_id: string };
  }
  profiles(): Promise<{ items: ModelProfile[] }> { return this.request("/model-profiles"); }
  saveProfile(payload: Record<string, unknown>): Promise<ModelProfile> { return this.request("/model-profiles", { method: "POST", body: JSON.stringify(payload) }); }
  updateProfile(profileId: string, expectedRevision: number, payload: Record<string, unknown>): Promise<ModelProfile> {
    return this.request(`/model-profiles/${profileId}`, { method: "PATCH", body: JSON.stringify({ ...payload, expected_revision: expectedRevision }) });
  }
  deleteProfile(profileId: string, expectedRevision: number): Promise<void> {
    return this.request(`/model-profiles/${profileId}?expected_revision=${expectedRevision}`, { method: "DELETE" }).then(() => undefined);
  }
  saveCredential(profileId: string, key: string): Promise<ModelProfile> { return this.request(`/model-profiles/${profileId}/credential`, { method: "PUT", body: JSON.stringify({ key }) }); }
  clearCredential(profileId: string): Promise<ModelProfile> { return this.request(`/model-profiles/${profileId}/credential`, { method: "DELETE" }); }
  probeProfile(profileId: string): Promise<{ ok: boolean; code?: string }> { return this.request(`/model-profiles/${profileId}/test`, { method: "POST", body: "{}" }); }
  geoSource(sourceId: string): Promise<GeoSourceState> { return this.request(`/geo/sources/${encodeURIComponent(sourceId)}`); }
  createGeoSearch(payload: GeoSearchRequest): Promise<GeoSearchState> { return this.request("/geo/searches", { method: "POST", body: JSON.stringify(payload) }); }
  private geoSearchPath(searchId: string, suffix = "", conversationId?: string): string {
    return `/geo/searches/${encodeURIComponent(searchId)}${suffix}${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""}`;
  }
  geoSearch(searchId: string, conversationId?: string): Promise<GeoSearchState> { return this.request(this.geoSearchPath(searchId, "", conversationId)); }
  nextGeoSearchPage(searchId: string, pageToken: string, revision: number, conversationId?: string): Promise<GeoSearchState> {
    return this.request(this.geoSearchPath(searchId, "/pages", conversationId), { method: "POST", body: JSON.stringify({ page_token: pageToken, revision }) });
  }
  selectGeoSearchResult(searchId: string, accession: string, revision: number, conversationId?: string): Promise<GeoSearchState> {
    return this.request(this.geoSearchPath(searchId, "/selection", conversationId), { method: "POST", body: JSON.stringify({ accession, revision }) });
  }
  cancelGeoSearch(searchId: string, conversationId?: string): Promise<GeoSearchState> { return this.request(this.geoSearchPath(searchId, "/cancel", conversationId), { method: "POST", body: "{}" }); }
  createGeoImport(sourceId: string, candidateId: string, revision: number): Promise<GeoImportState> {
    return this.request(`/geo/sources/${encodeURIComponent(sourceId)}/imports`, { method: "POST", body: JSON.stringify({ candidate_id: candidateId, revision }) });
  }
  geoImport(importId: string): Promise<GeoImportState> { return this.request(`/geo/imports/${encodeURIComponent(importId)}`); }
  submitGeoSelection(importId: string, selection: GeoSelection): Promise<GeoImportState> {
    return this.request(`/geo/imports/${encodeURIComponent(importId)}/selection`, { method: "POST", body: JSON.stringify(selection) });
  }
  cancelGeoImport(importId: string): Promise<GeoImportState> { return this.request(`/geo/imports/${encodeURIComponent(importId)}/cancel`, { method: "POST", body: "{}" }); }
  skillRoot(): Promise<{ root: string; configured: boolean }> { return this.request("/extensions/skill-roots"); }
  setSkillRoot(root: string): Promise<{ root: string; configured: boolean }> { return this.request("/extensions/skill-roots", { method: "PATCH", body: JSON.stringify({ root }) }); }
  skills(): Promise<{ items: SkillRecord[] }> { return this.request("/extensions/skills"); }
  rescanSkills(): Promise<{ items: SkillRecord[]; errors: Array<{ relative_path: string; code: string }> }> { return this.request("/extensions/skills/rescan", { method: "POST", body: "{}" }); }
  skill(skillId: string): Promise<SkillDetail> { return this.request(`/extensions/skills/${encodeURIComponent(skillId)}`); }
  setSkillEnabled(skillId: string, enabled: boolean, expectedHash?: string): Promise<{ record: SkillRecord }> { return this.request(`/extensions/skills/${encodeURIComponent(skillId)}`, { method: "PATCH", body: JSON.stringify({ enabled, ...(enabled ? { expected_hash: expectedHash } : {}) }) }); }
  mcpServers(): Promise<{ items: McpServer[] }> { return this.request("/extensions/mcp/servers"); }
  createMcpServer(payload: Record<string, unknown>): Promise<McpServer> { return this.request("/extensions/mcp/servers", { method: "POST", body: JSON.stringify(payload) }); }
  updateMcpServer(serverId: string, expectedRevision: number, payload: Record<string, unknown>): Promise<McpServer> { return this.request(`/extensions/mcp/servers/${encodeURIComponent(serverId)}`, { method: "PATCH", body: JSON.stringify({ ...payload, expected_revision: expectedRevision }) }); }
  setMcpCredential(serverId: string, ref: string, value: string): Promise<{ configured: boolean; ref: string }> { return this.request(`/extensions/mcp/servers/${encodeURIComponent(serverId)}/credential`, { method: "PUT", body: JSON.stringify({ ref, value }) }); }
  deleteMcpCredential(serverId: string, ref = "default"): Promise<{ configured: boolean; ref: string }> { return this.request(`/extensions/mcp/servers/${encodeURIComponent(serverId)}/credential?ref=${encodeURIComponent(ref)}`, { method: "DELETE" }); }
  connectMcpServer(serverId: string): Promise<{ server_id: string; protocol_version?: string | null }> { return this.request(`/extensions/mcp/servers/${encodeURIComponent(serverId)}/connect`, { method: "POST", body: "{}" }); }
  disconnectMcpServer(serverId: string): Promise<{ server_id: string; connected: boolean }> { return this.request(`/extensions/mcp/servers/${encodeURIComponent(serverId)}/disconnect`, { method: "POST", body: "{}" }); }
  tools(): Promise<{ items: ToolDescriptor[] }> { return this.request("/extensions/tools"); }
  setToolPolicy(name: string, policy: ToolPolicy, expectedCapabilityRevision: string): Promise<ToolDescriptor> { return this.request(`/extensions/tools/${encodeURIComponent(name)}`, { method: "PATCH", body: JSON.stringify({ policy, expected_capability_revision: expectedCapabilityRevision }) }); }
  decideToolCall(callId: string, approvalId: string, decision: "approve" | "deny", capabilityRevision: string, argumentsHash: string): Promise<Record<string, unknown>> { return this.request(`/extensions/calls/${encodeURIComponent(callId)}/decision`, { method: "POST", body: JSON.stringify({ approval_id: approvalId, decision, capability_revision: capabilityRevision, arguments_hash: argumentsHash }) }); }

  knowledgeBases(): Promise<{ items: KnowledgeBase[] }> { return this.request("/knowledge/bases"); }
  wikiPreflight(base: string, payload: WikiRequest): Promise<WikiPreflight> { return this.request(`${wikiPath(base)}/preflight`, { method: "POST", body: JSON.stringify(payload) }); }
  wikiBuild(base: string, payload: WikiRequest, retryId?: string): Promise<WikiJob> { return this.request(`${wikiPath(base)}/${retryId ? `jobs/${encodeURIComponent(retryId)}/retry` : "build"}`, { method: "POST", body: JSON.stringify(payload) }); }
  wikiStatus(base: string): Promise<WikiJob | null> { return this.request(`${wikiPath(base)}/status`); }
  wikiCancel(base: string, job: string): Promise<WikiJob> { return this.request(`${wikiPath(base)}/jobs/${encodeURIComponent(job)}/cancel`, { method: "POST", body: "{}" }); }
  wikiPages(base: string): Promise<WikiList> { return this.request(`${wikiPath(base)}/pages`); }
  wikiPage(base: string, page: string): Promise<WikiPage> { return this.request(`${wikiPath(base)}/pages/${encodeURIComponent(page)}`); }
  wikiEvidence(base: string, page: string, chunk: string): Promise<EvidencePreview> { return this.request(`${wikiPath(base)}/pages/${encodeURIComponent(page)}/evidence/${encodeURIComponent(chunk)}`); }
  wikiUrl(base: string, page: string, suffix: string): string { return `${this.base}${wikiPath(base)}/pages/${encodeURIComponent(page)}/${suffix}`; }
  createKnowledgeBase(name: string): Promise<KnowledgeBase> { return this.request("/knowledge/bases", { method: "POST", body: JSON.stringify({ name }) }); }
  renameKnowledgeBase(id: string, name: string): Promise<KnowledgeBase> { return this.request(`/knowledge/bases/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify({ name }) }); }
  deleteKnowledgeBase(id: string): Promise<void> { return this.request(`/knowledge/bases/${encodeURIComponent(id)}`, { method: "DELETE" }); }
  knowledgeDocuments(id: string): Promise<{ items: KnowledgeDocument[] }> { return this.request(`/knowledge/bases/${encodeURIComponent(id)}/documents`); }
  knowledgeReadiness(retrieval = false): Promise<KnowledgeReady> { return this.request(`/knowledge/${retrieval ? "retrieval/" : ""}readiness`); }
  knowledgeUploadLimits(): Promise<KnowledgeUploadLimits> { return this.request("/knowledge/limits"); }
  knowledgeIndex(id: string): Promise<IndexState> { return this.request(`/knowledge/documents/${encodeURIComponent(id)}/index`); }
  indexKnowledgeDocument(id: string): Promise<KnowledgeJob> { return this.request(`/knowledge/documents/${encodeURIComponent(id)}/index`, { method: "POST" }); }
  retryKnowledgeDocument(id: string): Promise<KnowledgeJob> { return this.request(`/knowledge/documents/${encodeURIComponent(id)}/retry`, { method: "POST" }); }
  deleteKnowledgeDocument(id: string): Promise<void> { return this.request(`/knowledge/documents/${encodeURIComponent(id)}`, { method: "DELETE" }); }
  cancelKnowledgeJob(id: string, index = false): Promise<KnowledgeJob> { return this.request(`/knowledge/${index ? "index-jobs" : "jobs"}/${encodeURIComponent(id)}/cancel`, { method: "POST" }); }
  async uploadKnowledgeDocuments(id: string, files: File[]): Promise<unknown> {
    const body = new FormData(); files.forEach((file) => body.append("files", file));
    const response = await fetch(`${this.base}/knowledge/bases/${encodeURIComponent(id)}/documents`, { method: "POST", body, headers: this.csrf ? { "X-CSRF-Token": this.csrf } : {} });
    if (!response.ok) { const failure = await response.json() as ErrorBody; throw new ApiError(failure.detail?.code ?? "PDF_UPLOAD_FAILED", response.status); }
    return response.json();
  }
  knowledgeTask(conversation: string, turn: string): Promise<KnowledgeTask> { return this.request(`${knowledgeTurnPath(conversation, turn)}/knowledge`); }
  knowledgeEvents(conversation: string, turn: string, signal: AbortSignal) { return readKnowledgeEvents(`${this.base}${knowledgeTurnPath(conversation, turn)}/knowledge/events`, signal); }
  evidencePreview(conversation: string, turn: string, chunk: string): Promise<EvidencePreview> { return this.request(`${knowledgeTurnPath(conversation, turn)}/evidence/${encodeURIComponent(chunk)}`); }
  evidenceUrl(conversation: string, turn: string, chunk: string, resource: "pdf" | "image" | "page"): string { return `${this.base}${knowledgeTurnPath(conversation, turn)}/evidence/${encodeURIComponent(chunk)}/${resource}`; }

  async *events(conversationId: string, signal?: AbortSignal): AsyncGenerator<WorkbenchEvent> {
    let after = 0; let delay = 250;
    while (!signal?.aborted) {
      try {
        const response = await fetch(`${this.base}/workbench/conversations/${conversationId}/events?after=${after}`, { headers: this.csrf ? { "X-CSRF-Token": this.csrf } : {}, signal });
        if (!response.ok || !response.body) throw new ApiError("EVENT_STREAM_FAILED", response.status);
        const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
        while (!signal?.aborted) {
          const part = await reader.read(); if (part.done) break;
          buffer += decoder.decode(part.value, { stream: true });
          const blocks = buffer.split("\n\n"); buffer = blocks.pop() ?? "";
          for (const block of blocks) { const event = parseEventBlock(block); if (event) { after = Math.max(after, event.seq); delay = 250; yield event; } }
        }
      } catch (error) { if (signal?.aborted) return; if (error instanceof ApiError && error.status === 422) throw error; }
      await new Promise((resolve) => setTimeout(resolve, delay)); delay = Math.min(delay * 2, 30_000);
    }
  }
}
