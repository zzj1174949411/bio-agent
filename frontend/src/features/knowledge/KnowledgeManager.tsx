import { useEffect, useState } from "react";
import { ApiClient } from "../../api/client";
import type { IndexState, KnowledgeBase, KnowledgeDocument, KnowledgeReady } from "../../api/knowledge";

const statusName: Record<string, string> = { QUEUED: "排队", PARSING: "解析中", PARSED: "解析完成，尚未索引", INDEXING: "索引中", READY: "可检索", FAILED: "失败", CANCELLED: "已取消" };

export function KnowledgeManager({ api, onChanged, onClose }: { api: ApiClient; onChanged: () => void; onClose: () => void }) {
  const [bases, setBases] = useState<KnowledgeBase[]>([]); const [selected, setSelected] = useState("");
  const [name, setName] = useState(""); const [rename, setRename] = useState(""); const [confirmDelete, setConfirmDelete] = useState(false);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]); const [indexes, setIndexes] = useState<Record<string, IndexState>>({});
  const [parser, setParser] = useState<KnowledgeReady | null>(null); const [retrieval, setRetrieval] = useState<KnowledgeReady | null>(null);
  const [files, setFiles] = useState<File[]>([]); const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const [loaded, setLoaded] = useState(false);
  const refresh = async () => { const result = await api.knowledgeBases(); setBases(result.items); setSelected((current) => result.items.some((base) => base.id === current) ? current : result.items[0]?.id ?? ""); onChanged(); };
  useEffect(() => { let live = true;
    void api.knowledgeBases().then((list) => { if (!live) return; setBases(list.items); setSelected(list.items[0]?.id ?? ""); setLoaded(true); }).catch(() => { if (live) setError("知识库列表读取失败，请重新打开此页。"); });
    void Promise.all([api.knowledgeReadiness(), api.knowledgeReadiness(true)]).then(([parse, index]) => { if (!live) return; setParser(parse); setRetrieval(index); }).catch(() => { if (live) setError("知识库状态读取失败，请检查后端连接。"); });
    return () => { live = false; };
  }, [api]);
  useEffect(() => {
    let live = true;
    setConfirmDelete(false); setFiles([]); setDocuments([]); setIndexes({}); setRename(bases.find((base) => base.id === selected)?.name ?? "");
    const load = async () => { if (!selected) return; try { const list = await api.knowledgeDocuments(selected); const states = await Promise.all(list.items.map(async (doc) => [doc.id, await api.knowledgeIndex(doc.id)] as const)); if (live) { setDocuments(list.items); setIndexes(Object.fromEntries(states)); } } catch { if (live) setError("文献状态读取失败，请刷新后重试。"); } };
    void load(); const timer = setInterval(() => void load(), 2000);
    return () => { live = false; clearInterval(timer); };
  }, [api, selected]);
  const act = async (operation: () => Promise<unknown>) => { setBusy(true); setError(""); try { await operation(); await refresh(); if (selected) { const list = await api.knowledgeDocuments(selected).catch(() => ({ items: [] })); setDocuments(list.items); } } catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败，请重试。"); } finally { setBusy(false); } };
  return <section className="knowledge-manager" aria-label="知识库管理">
    <div className="settings-header"><h1>知识库管理</h1><button onClick={onClose}>返回聊天</button></div>
    <p>PDF 在本机解析并建立索引。只有“可检索 READY”文献能参与回答。</p>
    <p><a href="/api/v1/workbench/knowledge-guide" target="_blank" rel="noreferrer">安装、准备模型与使用说明</a></p>
    <div className="knowledge-readiness">{[["本地解析", parser], ["本地检索", retrieval]].map(([label, value]) => { const state = value as KnowledgeReady | null; return <p key={String(label)}>{String(label)}：{state?.ready ? "已就绪" : state?.code ?? "检查中…"}{state && !state.ready && <span>；请按安装说明准备依赖与权重。{state.prepare_command && <code>{state.prepare_command}</code>}</span>}</p>; })}</div>
    {error && <p role="alert" className="error">{error}</p>}
    <form onSubmit={(event) => { event.preventDefault(); void act(async () => { const base = await api.createKnowledgeBase(name.trim()); setSelected(base.id); setName(""); }); }}><label>新知识库名称<input aria-label="新知识库名称" maxLength={200} value={name} onChange={(event) => setName(event.target.value)} /></label><button disabled={busy || !loaded || !name.trim()}>创建知识库</button></form>
    <label>管理知识库<select aria-label="管理知识库" value={selected} onChange={(event) => setSelected(event.target.value)}><option value="">请选择知识库</option>{bases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}</select></label>
    {selected && <><div className="knowledge-toolbar"><label>知识库名称<input aria-label="知识库名称" maxLength={200} value={rename} onChange={(event) => setRename(event.target.value)} /></label><button disabled={busy || !rename.trim()} onClick={() => void act(() => api.renameKnowledgeBase(selected, rename.trim()))}>改名</button><button disabled={busy} onClick={() => setConfirmDelete(true)}>删除知识库</button>{confirmDelete && <span>库内文献与历史证据将失效。<button disabled={busy} onClick={() => void act(() => api.deleteKnowledgeBase(selected))}>确认删除库内文献</button><button onClick={() => setConfirmDelete(false)}>保留知识库</button></span>}</div>
    <form onSubmit={(event) => { event.preventDefault(); void act(async () => { await api.uploadKnowledgeDocuments(selected, files); setFiles([]); }); }}><label>本地 PDF（每批最多 4 份，每份 10 MiB）<input aria-label="本地 PDF" type="file" multiple accept="application/pdf,.pdf" disabled={busy || !parser?.ready} onChange={(event) => setFiles(Array.from(event.target.files ?? []))} /></label><button disabled={busy || !parser?.ready || files.length < 1 || files.length > 4 || files.some((file) => file.size > 10 * 1024 * 1024)}>上传并解析</button><span>{files.map((file) => file.name).join("、")}</span></form>
    <div className="knowledge-documents">{documents.length === 0 && <p>此库暂无文献。</p>}{documents.map((doc) => { const index = indexes[doc.id]?.latest_job; const parsing = ["QUEUED", "PARSING"].includes(doc.status); const indexing = index && ["QUEUED", "INDEXING"].includes(index.status); return <article key={doc.id} className="knowledge-document"><h2>{doc.filename}</h2><p role="status">{statusName[doc.status] ?? doc.status} · {doc.status}</p><p>解析：{doc.job.stage} · {doc.job.progress}%{doc.job.error_code && ` · ${doc.job.error_code}`}</p>{index && <p>索引：{statusName[index.status]} · {index.progress}%{index.error_code && ` · ${index.error_code}`}</p>}{doc.warnings.length > 0 && <p className="hint">版面、OCR 或表格关联需要核对原文。</p>}<div className="knowledge-toolbar">{parsing && <button disabled={busy} onClick={() => void act(() => api.cancelKnowledgeJob(doc.job.id))}>取消解析</button>}{["FAILED", "CANCELLED"].includes(doc.status) && <button disabled={busy || !parser?.ready} onClick={() => void act(() => api.retryKnowledgeDocument(doc.id))}>重试解析</button>}{indexing ? <button disabled={busy} onClick={() => void act(() => api.cancelKnowledgeJob(index.id, true))}>取消索引</button> : doc.published_revision && <button disabled={busy || !retrieval?.ready} onClick={() => void act(() => api.indexKnowledgeDocument(doc.id))}>{doc.index_revision ? "重建索引" : index?.status === "FAILED" ? "重试索引" : "建立索引"}</button>}<button disabled={busy} onClick={() => void act(() => api.deleteKnowledgeDocument(doc.id))}>删除文献</button></div></article>; })}</div></>}
  </section>;
}
