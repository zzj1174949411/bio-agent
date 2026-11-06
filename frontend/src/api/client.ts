import type { Conversation, GeoImportState, GeoSelection, GeoSourceState, Message, ModelProfile, Project, Turn } from "./types";
import { parseEventBlock, type WorkbenchEvent } from "./events";

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
  projects(): Promise<{ items: Project[] }> { return this.request("/workbench/projects"); }
  createProject(title: string): Promise<Project> { return this.request("/workbench/projects", { method: "POST", body: JSON.stringify({ title }) }); }
  updateProject(id: string, payload: { title?: string; archived?: boolean }): Promise<Project> { return this.request(`/workbench/projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) }); }
  conversations(projectId: string): Promise<{ items: Conversation[] }> { return this.request(`/workbench/conversations?project_id=${encodeURIComponent(projectId)}`); }
  createConversation(projectId: string, title: string): Promise<Conversation> { return this.request("/workbench/conversations", { method: "POST", body: JSON.stringify({ project_id: projectId, title }) }); }
  updateConversation(id: string, payload: { title?: string; archived?: boolean }): Promise<Conversation> { return this.request(`/workbench/conversations/${id}`, { method: "PATCH", body: JSON.stringify(payload) }); }
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
  artifacts(runId: string): Promise<{ run_id: string; artifacts: Array<{ artifact_id: string; sha256: string }> }> { return this.request(`/runs/${runId}/artifacts`); }
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
  createGeoImport(sourceId: string, candidateId: string, revision: number): Promise<GeoImportState> {
    return this.request(`/geo/sources/${encodeURIComponent(sourceId)}/imports`, { method: "POST", body: JSON.stringify({ candidate_id: candidateId, revision }) });
  }
  geoImport(importId: string): Promise<GeoImportState> { return this.request(`/geo/imports/${encodeURIComponent(importId)}`); }
  submitGeoSelection(importId: string, selection: GeoSelection): Promise<GeoImportState> {
    return this.request(`/geo/imports/${encodeURIComponent(importId)}/selection`, { method: "POST", body: JSON.stringify(selection) });
  }
  cancelGeoImport(importId: string): Promise<GeoImportState> { return this.request(`/geo/imports/${encodeURIComponent(importId)}/cancel`, { method: "POST", body: "{}" }); }

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
