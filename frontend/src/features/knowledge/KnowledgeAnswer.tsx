import { EvidenceSurface } from "../../components/FilePreview";
import { useEffect, useRef, useState } from "react";
import { ApiClient } from "../../api/client";
import type { EvidencePreview, KnowledgeTask } from "../../api/knowledge";
import { modelFailure } from "../models/errors";

const labels: Record<string, string> = { QUEUED: "知识问答排队", RETRIEVING: "检索开始", GENERATING: "依据命中证据生成回答", VALIDATING: "验证引用", COMPLETED: "引用验证完成", NO_EVIDENCE: "未找到可用证据，请先完成索引或调整问题", CANCELLED: "知识问答已取消", FAILED: "知识问答失败" };
const modeLabels = { rag: "原文 RAG", hybrid: "原文 + Wiki 混合", wiki: "Wiki 消融" };

function EvidenceTable({ table }: { table: NonNullable<EvidencePreview["element"]["table"]> }) {
  const rows = Array.from({ length: Math.min(table.num_rows, 500) }, (_, row) => table.table_cells.filter((cell) => cell.start_row_offset_idx === row).sort((a, b) => a.start_col_offset_idx - b.start_col_offset_idx));
  return <div className="evidence-table"><table><tbody>{rows.map((cells, index) => <tr key={index}>{cells.map((cell, position) => cell.column_header || cell.row_header ? <th key={position} colSpan={cell.col_span} rowSpan={cell.row_span}>{cell.text}</th> : <td key={position} colSpan={cell.col_span} rowSpan={cell.row_span}>{cell.text}</td>)}</tr>)}</tbody></table>{table.num_rows > 500 && <p>表格较长，请打开 PDF 核查完整内容。</p>}</div>;
}

export function KnowledgeAnswer({ api, conversationId, turnId }: { api: ApiClient; conversationId: string; turnId: string }) {
  const [task, setTask] = useState<KnowledgeTask | null>(null); const [text, setText] = useState(""); const [status, setStatus] = useState("QUEUED"); const [count, setCount] = useState<number | null>(null);
  const [names, setNames] = useState<Record<string, string>>({}); const [error, setError] = useState(""); const [preview, setPreview] = useState<{ chunk: string; value: EvidencePreview; image: boolean } | null>(null);
  const currentTurn = useRef(""); currentTurn.current = `${conversationId}/${turnId}`;
  useEffect(() => {
    const controller = new AbortController(); let namesLoaded = false; let loading = false;
    setTask(null); setText(""); setPreview(null); setError(""); setCount(null); setStatus("QUEUED");
    const refresh = async () => {
      if (loading) return; loading = true;
      try { const current = await api.knowledgeTask(conversationId, turnId); if (controller.signal.aborted) return;
        setTask(current); setStatus(current.status); setError("");
        if (["FAILED", "CANCELLED"].includes(current.status)) { setText(""); setPreview(null); }
        else if (current.status === "COMPLETED") setText(current.answer ?? "");
        if (!namesLoaded) { namesLoaded = true; const lists = await Promise.all(current.fixed_scope.map((id) => api.knowledgeDocuments(id).catch(() => ({ items: [] })))); if (!controller.signal.aborted) setNames(Object.fromEntries(lists.flatMap((list) => list.items.map((doc) => [doc.id, doc.filename])))); }
      } catch { if (!controller.signal.aborted) { setError("无法核验当前证据，请检查连接后重试。"); setPreview(null); } } finally { loading = false; }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 2000); const focus = () => void refresh(); window.addEventListener("focus", focus);
    void (async () => { try { for await (const event of api.knowledgeEvents(conversationId, turnId, controller.signal)) {
      if (controller.signal.aborted) return;
      if (event.kind === "status" && event.data.status) setStatus(event.data.status);
      if (event.kind === "retrieval.completed") setCount(event.data.count ?? 0);
      if (event.kind === "answer.delta") setText((value) => value + (event.data.text ?? ""));
      if (["completed", "failed", "cancelled"].includes(event.kind)) await refresh();
    } } catch { if (!controller.signal.aborted) setError("事件连接失败，正在核验任务状态。"); } })();
    return () => { controller.abort(); clearInterval(timer); window.removeEventListener("focus", focus); };
  }, [api, conversationId, turnId]);
  const revoked = task?.error_code === "EVIDENCE_STALE";
  const open = async (chunk: string, image: boolean) => { const owner = `${conversationId}/${turnId}`; try { const value = await api.evidencePreview(conversationId, turnId, chunk); if (currentTurn.current === owner) setPreview({ chunk, value, image }); } catch { if (currentTurn.current !== owner) return; setTask((current) => current ? { ...current, status: "FAILED", error_code: "EVIDENCE_STALE", answer: null, citations: [] } : current); setText(""); setPreview(null); } };
  return <section className="knowledge-answer" aria-label="文献回答">
    <p role="status">{revoked ? "证据已失效，请重新发送问题。" : labels[status] ?? status}{count !== null && ` · 检索完成：${count} 条命中`}</p>
    <small>操作状态与已验证答案分段；答案在完整引用校验后展示，并非原始模型 token 流。</small>
    {task && <div className="knowledge-audit" aria-label="检索模式与上下文审计">
      <p>实际模式：{modeLabels[task.actual_mode ?? "rag"]} · 请求模式：{modeLabels[task.requested_mode ?? "rag"]}{task.fallback_reason && ` · 回退原因：${task.fallback_reason}`}</p>
      {task.audit && <details><summary>两路检索与模型上下文</summary><p>检索候选：原文 {task.audit.original_retrieved} 条，Wiki {task.audit.wiki_retrieved} 页，Wiki 回源 {task.audit.linked_original_retrieved} 条。</p><p>实际送入模型：原文 {task.audit.original_sent} 条 / {task.audit.original_bytes} bytes，Wiki {task.audit.wiki_sent} 页 / {task.audit.wiki_bytes} bytes；上下文共 {task.audit.context_bytes} bytes。</p><small>引用校验用于确认原文身份与存活版本；语义与数值仍需核查原文。</small></details>}
    </div>}
    {error && <p role="alert">{error}</p>}
    {!revoked && !error && !["FAILED", "CANCELLED"].includes(task?.status ?? "") && <>
      <p className="knowledge-answer-text">{text}</p>
      {!!task?.wiki_navigation?.length && <details className="wiki-navigation-used"><summary>本轮 Wiki 派生导航（{task.wiki_navigation.length} 页）</summary><p>AI 派生整理，不算独立研究；最终事实与数值以以下原文证据为准。</p>{task.wiki_navigation.map((page) => <article key={page.page_id}><h3>{page.title}</h3><p>{page.statements.join("\n")}</p><small>{page.human_reviewed ? "已标记人工复核" : "尚未人工复核"}</small></article>)}</details>}
      {task?.citations.map((ref) => { const hit = task.evidence.find((item) => item.reference.chunk_id === ref.chunk_id); if (!hit) return null; return <article className="evidence" key={ref.chunk_id}><h3>{names[ref.document_id] ?? "本地文献"} · PDF 第 {ref.page} 页</h3><p>{hit.chunk.section.join(" › ")}</p><blockquote>{hit.chunk.text}</blockquote>{hit.chunk.context && <details><summary>相邻原文上下文</summary><p>{hit.chunk.context}</p></details>}<button onClick={() => void open(ref.chunk_id, false)}>打开 PDF 第 {ref.page} 页</button>{hit.chunk.kind === "table" && <button onClick={() => void open(ref.chunk_id, true)}>查看表格结构</button>}{hit.chunk.asset_id && <button onClick={() => void open(ref.chunk_id, true)}>查看裁剪图片</button>}{hit.chunk.kind === "picture" && <p className="hint">仅依据图注 / OCR；未进行视觉理解（not_performed），不能读取柱高或精确图表数值。</p>}</article>; })}
    </>}
    {task?.status === "FAILED" && !revoked && <p role="alert">{modelFailure(task.error_code)}</p>}
    {preview && !revoked && !error && <EvidenceSurface title="原文证据预览" onClose={() => setPreview(null)}><button onClick={() => setPreview(null)}>关闭预览</button><h3>PDF 第 {preview.value.page} 页 · 原文证据</h3>{preview.image ? <>{preview.value.element.table && <EvidenceTable table={preview.value.element.table} />}<p>{preview.value.element.text}</p><p>{preview.value.element.captions.join("\n")}</p><p>{preview.value.element.footnotes.join("\n")}</p><p>{preview.value.element.ocr_text}</p>{task?.evidence.find((hit) => hit.chunk.id === preview.chunk)?.chunk.asset_id && <img src={api.evidenceUrl(conversationId, turnId, preview.chunk, "image")} alt="论文图表裁剪" />}</> : <><a href={api.evidenceUrl(conversationId, turnId, preview.chunk, "pdf")} download="document.pdf">下载原始 PDF</a><img className="pdf-page" alt={`PDF 第 ${preview.value.page} 页`} src={api.evidenceUrl(conversationId, turnId, preview.chunk, "page")} onError={() => setError("PDF 页预览不可用，请检查本地解析依赖并重新打开。")} /></>}{preview.value.warnings.length > 0 && <p className="hint">OCR、双栏阅读顺序及跨页表格可能不完整，请对照 PDF 核查。</p>}</EvidenceSurface>}
  </section>;
}
