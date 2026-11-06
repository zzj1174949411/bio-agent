import { useEffect, useRef, useState } from "react";
import { ApiClient } from "../../api/client";
import { KnowledgeWiki } from "./KnowledgeWiki";
import type { IndexState, KnowledgeBase, KnowledgeDocument, KnowledgeReady, KnowledgeUploadLimits } from "../../api/knowledge";

const statusName: Record<string, string> = { QUEUED: "排队", PARSING: "解析中", PARSED: "解析完成，尚未索引", INDEXING: "索引中", READY: "可检索", FAILED: "失败", CANCELLED: "已取消" };
type UploadItem = { file: File; status: "pending" | "uploading" | "uploaded" | "failed"; error?: string };
const uploadStatus = { pending: "尚未上传", uploading: "上传中", uploaded: "已上传，解析状态见下方文献列表", failed: "上传失败" };
const mib = (bytes: number) => bytes / 1024 ** 2;

export function KnowledgeManager({ api, onChanged, onClose }: { api: ApiClient; onChanged: () => void; onClose: () => void }) {
  const [bases, setBases] = useState<KnowledgeBase[]>([]); const [selected, setSelected] = useState("");
  const [wikiOpen, setWikiOpen] = useState(false);
  const [name, setName] = useState(""); const [rename, setRename] = useState(""); const [confirmDelete, setConfirmDelete] = useState(false);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]); const [indexes, setIndexes] = useState<Record<string, IndexState>>({});
  const [parser, setParser] = useState<KnowledgeReady | null>(null); const [retrieval, setRetrieval] = useState<KnowledgeReady | null>(null);
  const [items, setItems] = useState<UploadItem[]>([]); const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [loaded, setLoaded] = useState(false);
  const [limits, setLimits] = useState<KnowledgeUploadLimits | null>(null); const [limitsError, setLimitsError] = useState("");
  const [parserError, setParserError] = useState(""); const [retrievalError, setRetrievalError] = useState("");
  const [uploading, setUploading] = useState(false); const [stopped, setStopped] = useState(false);
  const uploadRef = useRef<{ stopped: boolean; base: string } | null>(null);
  const viewRevision = useRef(0);
  const refresh = async () => { const result = await api.knowledgeBases(); setBases(result.items); setSelected((current) => result.items.some((base) => base.id === current) ? current : result.items[0]?.id ?? ""); onChanged(); };
  useEffect(() => { let live = true;
    void api.knowledgeBases().then((list) => { if (!live) return; setBases(list.items); setSelected(list.items[0]?.id ?? ""); setLoaded(true); }).catch(() => { if (live) setError("知识库列表读取失败，请重新打开此页。"); });
    void api.knowledgeReadiness().then((state) => { if (live) setParser(state); }).catch(() => { if (live) setParserError("本地解析状态读取失败，请检查后端连接并重新打开此页。"); });
    void api.knowledgeReadiness(true).then((state) => { if (live) setRetrieval(state); }).catch(() => { if (live) setRetrievalError("本地检索状态读取失败，请检查后端连接并重新打开此页。"); });
    void api.knowledgeUploadLimits().then((value) => { if (live) setLimits(value); }).catch(() => { if (live) setLimitsError("上传限制读取失败，请确认后端已更新并重新打开此页。"); });
    return () => { live = false; };
  }, [api]);
  useEffect(() => {
    let live = true;
    viewRevision.current += 1;
    setWikiOpen(false);
    setConfirmDelete(false); setItems([]); setStopped(false); setDocuments([]); setIndexes({}); setRename(bases.find((base) => base.id === selected)?.name ?? "");
    const load = async () => { if (!selected) return; try { const list = await api.knowledgeDocuments(selected); const states = await Promise.all(list.items.map(async (doc) => [doc.id, await api.knowledgeIndex(doc.id)] as const)); if (live) { setDocuments(list.items); setIndexes(Object.fromEntries(states)); } } catch { if (live) setError("文献状态读取失败，请刷新后重试。"); } };
    void load(); const timer = setInterval(() => void load(), 2000);
    return () => { live = false; viewRevision.current += 1; clearInterval(timer); if (uploadRef.current) uploadRef.current.stopped = true; uploadRef.current = null; };
  }, [api, selected]);
  const act = async (operation: () => Promise<unknown>) => { setBusy(true); setError(""); try { await operation(); await refresh(); if (selected) { const list = await api.knowledgeDocuments(selected).catch(() => ({ items: [] })); setDocuments(list.items); } } catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败，请重试。"); } finally { setBusy(false); } };
  const fileIssue = (file: File) => !file.name.toLowerCase().endsWith(".pdf") ? "仅支持 PDF 文件" : limits && file.size > limits.max_pdf_bytes ? `超过单份 ${mib(limits.max_pdf_bytes)} MiB，已跳过；请选择较小的 PDF。` : "";
  const pending = items.filter((item) => item.status === "pending" && !fileIssue(item.file));
  const failed = items.filter((item) => item.status === "failed" && !fileIssue(item.file));
  const uploadedCount = items.filter((item) => item.status === "uploaded").length;
  const skippedCount = items.filter((item) => fileIssue(item.file)).length;
  const issues: string[] = [];
  if (busy) issues.push("操作进行中，请稍候。");
  if (!limits) issues.push(limitsError || "正在读取上传限制…");
  if (!parser?.ready) issues.push(parserError || (parser ? `本地解析尚未就绪（${parser.code}），请按上方安装说明准备。` : "正在检查本地解析状态…"));
  if (!items.length) issues.push("请选择 PDF。");
  if (limits && items.length > limits.max_files_per_selection) issues.push(`已选择 ${items.length} 份，超过每次最多 ${limits.max_files_per_selection} 份。`);
  const canUpload = issues.length === 0;
  const upload = async (retry = false) => {
    if (!canUpload || uploadRef.current) return;
    const targets = retry ? failed : pending;
    if (!targets.length) return;
    const context = { base: selected, stopped: false }; uploadRef.current = context;
    const revision = viewRevision.current;
    setBusy(true); setUploading(true); setStopped(false); setError("");
    const live = () => uploadRef.current === context;
    const update = (file: File, status: UploadItem["status"], error?: string) => { if (live()) setItems((current) => current.map((item) => item.file === file ? { ...item, status, error } : item)); };
    for (const item of targets) {
      if (context.stopped) break;
      update(item.file, "uploading");
      try { await api.uploadKnowledgeDocuments(context.base, [item.file]); update(item.file, "uploaded"); }
      catch (reason) { update(item.file, "failed", reason instanceof Error ? reason.message : "请求失败，请重试。"); }
    }
    if (!live()) return;
    setStopped(context.stopped); uploadRef.current = null; setBusy(false); setUploading(false);
    onChanged();
    void api.knowledgeDocuments(context.base).then((result) => { if (viewRevision.current === revision && !uploadRef.current) setDocuments(result.items); }).catch(() => undefined);
  };
  return <section className="knowledge-manager" aria-label="知识库管理">
    <div className="settings-header"><h1>知识库管理</h1><button onClick={onClose}>返回聊天</button></div>
    <p>PDF 在本机解析并建立索引。只有“可检索 READY”文献能参与回答。</p>
    <p><a href="/api/v1/workbench/knowledge-guide" target="_blank" rel="noreferrer">安装、准备模型与使用说明</a></p>
    <div className="knowledge-readiness">{[["本地解析", parser, parserError], ["本地检索", retrieval, retrievalError]].map(([label, value, failure]) => { const state = value as KnowledgeReady | null; return <p key={String(label)}>{String(label)}：{failure ? String(failure) : state?.ready ? "已就绪" : state?.code ?? "检查中…"}{state && !state.ready && <span>；请按安装说明准备依赖与权重。{state.prepare_command && <code>{state.prepare_command}</code>}</span>}</p>; })}</div>
    {error && <p role="alert" className="error">{error}</p>}
    <form onSubmit={(event) => { event.preventDefault(); void act(async () => { const base = await api.createKnowledgeBase(name.trim()); setSelected(base.id); setName(""); }); }}><label>新知识库名称<input aria-label="新知识库名称" maxLength={200} value={name} onChange={(event) => setName(event.target.value)} /></label><button disabled={busy || !loaded || !name.trim()}>创建知识库</button></form>
    <label>管理知识库<select aria-label="管理知识库" disabled={busy} value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">请选择知识库</option>{bases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}</select></label>
    {selected && <><div className="knowledge-toolbar"><label>知识库名称<input aria-label="知识库名称" maxLength={200} value={rename} onChange={(event) => setRename(event.target.value)} /></label><button disabled={busy || !rename.trim()} onClick={() => void act(() => api.renameKnowledgeBase(selected, rename.trim()))}>改名</button><button disabled={busy} onClick={() => setConfirmDelete(true)}>删除知识库</button>{confirmDelete && <span>库内文献与历史证据将失效。<button disabled={busy} onClick={() => void act(() => api.deleteKnowledgeBase(selected))}>确认删除库内文献</button><button onClick={() => setConfirmDelete(false)}>保留知识库</button></span>}</div>
    <form className="knowledge-upload" onSubmit={(event) => { event.preventDefault(); void upload(); }}><label>本地 PDF{limits && `（每次最多 ${limits.max_files_per_selection} 份，每份 ${mib(limits.max_pdf_bytes)} MiB）`}<input aria-label="本地 PDF" aria-describedby="upload-feedback" type="file" multiple accept="application/pdf,.pdf" disabled={busy || !parser?.ready || !limits} onChange={(event) => { setStopped(false); setItems(Array.from(event.target.files ?? []).map((file) => ({ file, status: "pending" }))); }} /></label><button aria-describedby="upload-feedback" disabled={!canUpload || !pending.length}>上传并解析</button>{failed.length > 0 && <button type="button" disabled={!canUpload} onClick={() => void upload(true)}>重试失败文件</button>}{uploading && <button type="button" onClick={() => { if (uploadRef.current) uploadRef.current.stopped = true; setStopped(true); }}>停止后续上传</button>}</form>
    <div id="upload-feedback" role="status">{issues.map((issue) => <p key={issue}>{issue}</p>)}{items.length > 0 && <p>已选择 {items.length} 份 · 已上传 {uploadedCount}/{items.length} · 失败 {failed.length} · 跳过 {skippedCount}</p>}{stopped && <p>已停止后续上传；当前请求结束后停止。已上传文件的解析仍在队列中，可在文献列表取消。</p>}{!busy && items.length > 0 && !pending.length && !failed.length && <p>{skippedCount ? uploadedCount ? "其余文件已上传；请替换被跳过的文件。" : "没有可上传文件；请替换被跳过的文件。" : "所选文件已全部上传。"}</p>}</div>
    {items.length > 0 && <ul className="knowledge-files" aria-label="所选 PDF">{items.map((item, index) => <li key={index} className={fileIssue(item.file) || item.status === "failed" ? "warning" : ""}>{item.file.name} · {mib(item.file.size).toFixed(2)} MiB · {fileIssue(item.file) || uploadStatus[item.status]}{item.error && `：${item.error}`}</li>)}</ul>}
    <div className="knowledge-documents">{documents.length === 0 && <p>此库暂无文献。</p>}{documents.map((doc) => { const index = indexes[doc.id]?.latest_job; const parsing = ["QUEUED", "PARSING"].includes(doc.status); const indexing = index && ["QUEUED", "INDEXING"].includes(index.status); return <article key={doc.id} className="knowledge-document"><h2>{doc.filename}</h2><p role="status">{statusName[doc.status] ?? doc.status} · {doc.status}</p><p>解析：{doc.job.stage} · {doc.job.progress}%{doc.job.error_code && ` · ${doc.job.error_code}`}</p>{index && <p>索引：{statusName[index.status]} · {index.progress}%{index.error_code && ` · ${index.error_code}`}</p>}{doc.warnings.length > 0 && <p className="hint">版面、OCR 或表格关联需要核对原文。</p>}<div className="knowledge-toolbar">{parsing && <button disabled={busy} onClick={() => void act(() => api.cancelKnowledgeJob(doc.job.id))}>取消解析</button>}{["FAILED", "CANCELLED"].includes(doc.status) && <button disabled={busy || !parser?.ready} onClick={() => void act(() => api.retryKnowledgeDocument(doc.id))}>重试解析</button>}{indexing ? <button disabled={busy} onClick={() => void act(() => api.cancelKnowledgeJob(index.id, true))}>取消索引</button> : doc.published_revision && <button disabled={busy || !retrieval?.ready} onClick={() => void act(() => api.indexKnowledgeDocument(doc.id))}>{doc.index_revision ? "重建索引" : index?.status === "FAILED" ? "重试索引" : "建立索引"}</button>}<button disabled={busy} onClick={() => void act(() => api.deleteKnowledgeDocument(doc.id))}>删除文献</button></div></article>; })}</div></>}
    {selected && <><button onClick={() => setWikiOpen((value) => !value)}>{wikiOpen ? "收起 Wiki" : "管理文献 Wiki"}</button>{wikiOpen && <KnowledgeWiki key={selected} api={api} base={selected} />}</>}
  </section>;
}
