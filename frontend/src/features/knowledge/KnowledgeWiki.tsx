import { EvidenceSurface } from "../../components/FilePreview";
import { useEffect, useRef, useState } from "react";
import { ApiClient } from "../../api/client";
import type { ModelProfile } from "../../api/types";
import type { WikiJob, WikiList, WikiPage, WikiPreflight } from "../../api/wiki";
import type { EvidencePreview } from "../../api/knowledge";
import { modelFailure } from "../models/errors";

const active = (job: WikiJob | null) => !!job && ["QUEUED", "BUILDING"].includes(job.status);
const kinds = { paper: "论文摘要", concept: "概念 / 方法", topic: "主题综合" };

export function KnowledgeWiki({ api, base }: { api: ApiClient; base: string }) {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]); const [profile, setProfile] = useState("");
  const [calls, setCalls] = useState(32); const [preflight, setPreflight] = useState<WikiPreflight | null>(null);
  const [list, setList] = useState<WikiList | null>(null); const [job, setJob] = useState<WikiJob | null>(null);
  const [page, setPage] = useState<WikiPage | null>(null); const [preview, setPreview] = useState<{ page: string; chunk: string; value: EvidencePreview } | null>(null);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const live = useRef(true);
  const pageId = useRef<string | null>(null); const navigation = useRef(0);
  useEffect(() => {
    live.current = true; let loading = false;
    void api.profiles().then((value) => { if (live.current) { setProfiles(value.items); setProfile(value.items[0]?.id ?? ""); } }).catch(() => { if (live.current) setError("Wiki 模型配置读取失败，请重新打开。"); });
    const refresh = async () => { if (loading) return; loading = true; try {
      const [pages, current] = await Promise.all([api.wikiPages(base), api.wikiStatus(base)]);
      if (!live.current) return; setList(pages); setJob(current);
      if (pageId.current && !pages.items.some((p) => p.id === pageId.current && p.status === "CURRENT")) { navigation.current++; pageId.current = null; setPage(null); setPreview(null); }
    } catch { if (live.current) { setError("Wiki 状态无法核验，请重新打开管理页。"); setPage(null); setPreview(null); } } finally { loading = false; } };
    void refresh(); const timer = setInterval(() => void refresh(), 1500);
    return () => { live.current = false; navigation.current++; clearInterval(timer); };
  }, [api, base]);
  const act = async (operation: () => Promise<void>) => { if (busy) return; setBusy(true); setError(""); try { await operation(); } catch (reason) { if (live.current) { setError(reason instanceof Error ? reason.message : "Wiki 操作失败"); setPreview(null); } } finally { if (live.current) setBusy(false); } };
  const inspect = async () => { const value = await api.wikiPreflight(base, { model_profile_id: profile, max_calls: calls }); if (live.current) setPreflight(value); };
  const start = async (retry = false) => { if (!preflight) return; const value = await api.wikiBuild(base, { model_profile_id: profile, max_calls: calls, preflight_sha256: preflight.preflight_sha256 }, retry ? job?.id : undefined); if (live.current) { setJob(value); setPreflight(null); } };
  const open = async (id: string) => { const revision = ++navigation.current; setPage(null); setPreview(null); pageId.current = id; const value = await api.wikiPage(base, id); if (live.current && revision === navigation.current) setPage(value); };
  const source = async (chunk: string) => { if (!page) return; const revision = navigation.current; const value = await api.wikiEvidence(base, page.id, chunk); if (live.current && revision === navigation.current) setPreview({ page: page.id, chunk, value }); };
  return <section className="wiki-manager" aria-label="文献 Wiki">
    <h2>文献 Wiki</h2><p>AI 生成，未经人工审定。引用匹配仅验证来源与原文一致，不保证语义蕴含。图像仅依据图注 / OCR，无视觉推断。</p>
    <p>上传不会自动构建或付费；点击预检后再明确启动。</p>
    <div className="knowledge-toolbar"><label>Wiki 构建模型<select aria-label="Wiki 构建模型" value={profile} disabled={busy || active(job)} onChange={(e) => { setProfile(e.target.value); setPreflight(null); }}><option value="">请选择配置</option>{profiles.map((p) => <option key={p.id} value={p.id}>{p.label} · {p.model}</option>)}</select></label>
      <label>Wiki 调用上限<input aria-label="Wiki 调用上限" type="number" min={1} max={256} value={calls} disabled={busy || active(job)} onChange={(e) => { setCalls(Number(e.target.value)); setPreflight(null); }} /></label>
      <button disabled={busy || active(job) || !profile || !Number.isInteger(calls) || calls < 1 || calls > 256} onClick={() => void act(inspect)}>预检 Wiki 构建</button>
      {active(job) && <button disabled={busy} onClick={() => void act(async () => { const value = await api.wikiCancel(base, job!.id); if (live.current) setJob(value); })}>停止 Wiki 构建</button>}
    </div>
    {error && <p role="alert">{error === "WIKI_PREFLIGHT_CHANGED" ? "库或配置已变化，请重新预检。" : error}</p>}
    {preflight && <div aria-label="Wiki 构建预检"><p>{preflight.base_name} · 文献 {preflight.document_count} 份，READY {preflight.ready_count} 份 · 模型 {preflight.model_snapshot.model}（revision {preflight.model_snapshot.revision}）</p>
      <p>预计 {preflight.required_calls} 次调用，上限 {calls}；每次输入最多 {preflight.profile.input_max_bytes} bytes，应用接收输出最多 {preflight.profile.output_max_bytes} bytes，供应商输出参数 {preflight.profile.output_token_limit} tokens。</p>
      <p>此配置协议限额未经实测，token / 费用上界未知；无隐式重试或模型切换。usage 缺失标为未知。</p>
      {preflight.coverage.map((c, i) => <p key={c.document_id}>文献 {i + 1}：{c.included_chunks}/{c.total_chunks} chunks，{c.included_text_bytes}/{c.total_text_bytes} 文本 bytes，{c.included_pages.length}/{c.total_pages} 页，{c.segments} 段{c.truncated ? " · 部分覆盖" : " · 全部 chunk 输入"}</p>)}
      <p>综合输入：{preflight.synthesis_chunks}/{preflight.synthesis_total_chunks} chunks；综合页只覆盖实际输入部分。</p>
      {preflight.required_calls > calls && <p role="alert">调用上限不足，任务将停止且不会发布部分版本。</p>}
      <button disabled={busy || active(job) || !preflight.ready_count} onClick={() => void act(() => start())}>{preflight.unchanged ? "确认无变化，跳过构建" : "确认开始 Wiki 构建"}</button>
      {job && ["FAILED", "CANCELLED"].includes(job.status) && <button disabled={busy} onClick={() => void act(() => start(true))}>重试 Wiki 构建</button>}
    </div>}
    {job && <p role="status">Wiki：{job.status} · {job.stage} · 已预留调用 {job.calls}/{job.request.max_calls} · usage {job.usage_complete && job.usage ? JSON.stringify(job.usage) : "未知或部分未知"}{job.error_code && ` · ${modelFailure(job.error_code)}`}</p>}
    {list && <><p>当前版本覆盖 {list.covered_document_count}/{list.document_count} 份文献{list.pending_update && " · 待更新 / 来源失效"}；概念与主题是派生内容，不算独立研究。</p><nav aria-label="Wiki 页面导航">{list.items.map((p) => <button key={p.id} disabled={busy || p.status === "STALE"} onClick={() => void act(() => open(p.id))}>{kinds[p.kind]}：{p.title}{p.status === "STALE" && "（来源已失效）"}</button>)}</nav></>}
    {page && <article aria-label="Wiki 页面"><h3>{page.title}</h3><p>AI 生成 · 未经人工审定 · generation {page.generation}</p><a href={api.wikiUrl(base, page.id, "export")} download="wiki-page.md">导出此页 Markdown</a>
      {page.coverage.map((c, i) => <p key={c.document_id}>此页输入文献 {i + 1}：{c.included_chunks}/{c.total_chunks} chunks · {c.included_pages.length}/{c.total_pages} 页{c.truncated && " · 部分覆盖"}</p>)}
      {page.statements.map((s, i) => <div key={i}><p>{s.text}</p><p>原研究条件：{s.conditions}</p>{s.candidate_disagreement && <p>候选分歧：需查原文，不作权威裁决。</p>}{s.citations.map((c, j) => <blockquote key={j}>{c.quote}<button onClick={() => void act(() => source(c.chunk_id))}>原文证据 · PDF 第 {c.reference.page} 页</button></blockquote>)}</div>)}
      <nav aria-label="Wiki 相关页面">{page.links.map((key) => { const target = list?.items.find((p) => p.key === key); return target && <button disabled={busy || target.status === "STALE"} key={key} onClick={() => void act(() => open(target.id))}>{target.title}</button>; })}</nav>
    </article>}
    {preview && <EvidenceSurface title="Wiki 原文预览" onClose={() => setPreview(null)}><button onClick={() => setPreview(null)}>关闭预览</button><h3>PDF 第 {preview.value.page} 页</h3><p>{preview.value.element.text}</p><a href={api.wikiUrl(base, preview.page, `evidence/${encodeURIComponent(preview.chunk)}/pdf`)} download="document.pdf">下载原始 PDF</a><img className="pdf-page" src={api.wikiUrl(base, preview.page, `evidence/${encodeURIComponent(preview.chunk)}/page`)} alt={`Wiki 原文 PDF 第 ${preview.value.page} 页`} onError={() => { setPreview(null); setError("Wiki 原文预览失效或不可用，请重新核验页面。"); }} /></EvidenceSurface>}
  </section>;
}
