import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ApiClient } from "../api/client";
import type { Artifact } from "../api/types";

type Selection = { kind: "file"; file: Artifact } | { kind: "evidence"; id: string; title: string; onClose: () => void } | { kind: "list" };
type PreviewHost = { openFile: (file: Artifact) => void; openList: () => void; openEvidence: (id: string, title: string, onClose: () => void) => void; closeEvidence: (id: string) => void; activeEvidence: string | null; target: HTMLElement | null };
const Context = createContext<PreviewHost | null>(null);
export const useFilePreview = () => useContext(Context);

function parseRows(text: string, delimiter: string): string[][] {
  const rows: string[][] = []; let row: string[] = [], value = "", quoted = false;
  for (let i = 0; i < text.length && rows.length < 101; i++) {
    const c = text[i];
    if (c === '"') { if (quoted && text[i + 1] === '"') { value += '"'; i++; } else quoted = !quoted; }
    else if (c === delimiter && !quoted) { row.push(value); value = ""; }
    else if (c === "\n" && !quoted) { row.push(value.replace(/\r$/, "")); rows.push(row.slice(0, 50)); row = []; value = ""; }
    else value += c;
  }
  if (value || row.length) rows.push([...row, value].slice(0, 50));
  return rows.slice(0, 100);
}
function FileContent({ api, file }: { api: ApiClient; file: Artifact }) {
  const [value, setValue] = useState<{ type: string; text: string; image: string } | null>(null); const [error, setError] = useState("");
  useEffect(() => { const controller = new AbortController(); let image = ""; setValue(null); setError("");
    void api.readArtifact(file.url, controller.signal).then(async ({ blob, type }) => {
      const isImage = ["image/png", "image/jpeg"].includes(type);
      const text = isImage ? "" : await blob.text(); if (controller.signal.aborted) return;
      image = isImage ? URL.createObjectURL(blob) : ""; setValue({ type, text, image });
    }).catch((reason) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "预览失败"); });
    return () => { controller.abort(); if (image) URL.revokeObjectURL(image); };
  }, [api, file.url]);
  if (error) return <p role="alert">{error}</p>;
  if (!value) return <p role="status">正在核验并读取文件…</p>;
  if (value.image) return <img src={value.image} alt={file.name} />;
  if (value.type === "text/html") return <iframe title="报告预览" sandbox="" srcDoc={'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data: blob:; style-src \'unsafe-inline\'">' + value.text} />;
  if (/\.(csv|tsv)$/i.test(file.name) || ["text/csv", "text/tab-separated-values"].includes(value.type)) {
    const rows = parseRows(value.text, file.name.endsWith(".tsv") ? "\t" : ",");
    return <><small>预览最多 100 行、50 列；完整内容请下载核查。</small><div className="file-table"><table><tbody>{rows.map((row, i) => <tr key={i}>{row.map((cell, j) => i === 0 ? <th key={j}>{cell}</th> : <td key={j}>{cell}</td>)}</tr>)}</tbody></table></div></>;
  }
  if (value.type.startsWith("text/") || value.type === "application/json") return <pre>{value.text}</pre>;
  return <p>此格式暂不支持内嵌预览，请下载原文件。</p>;
}
export function FilePreviewProvider({ api, files, children }: { api: ApiClient; files: Artifact[]; children: ReactNode }) {
  const [selection, setSelection] = useState<Selection | null>(null); const [tabs, setTabs] = useState<Artifact[]>([]); const [target, setTarget] = useState<HTMLDivElement | null>(null);
  const openFile = useCallback((file: Artifact) => { setTabs((current) => current.some((item) => item.url === file.url) ? current : [...current, file]); setSelection({ kind: "file", file }); }, []);
  const openList = useCallback(() => setSelection({ kind: "list" }), []);
  const openEvidence = useCallback((id: string, title: string, onClose: () => void) => setSelection({ kind: "evidence", id, title, onClose }), []);
  const closeEvidence = useCallback((id: string) => setSelection((current) => current?.kind === "evidence" && current.id === id ? null : current), []);
  const host = useMemo(() => ({ openFile, openList, openEvidence, closeEvidence, activeEvidence: selection?.kind === "evidence" ? selection.id : null, target }), [openFile, openList, openEvidence, closeEvidence, selection, target]);
  const close = () => { if (selection?.kind === "evidence") selection.onClose(); setSelection(null); };
  return <Context.Provider value={host}><div className={`workspace-split${selection ? " preview-open" : ""}`}>{children}{selection && <aside className="file-preview" aria-label="文件预览"><header><button onClick={openList}>对话文件</button><button aria-label="关闭文件预览" onClick={close}>关闭</button></header>{tabs.length > 0 && <nav aria-label="已打开文件">{tabs.map((file) => <button key={file.url} aria-pressed={selection.kind === "file" && selection.file.url === file.url} onClick={() => openFile(file)}>{file.name}</button>)}</nav>}<div className="file-body">{selection.kind === "list" ? <><h2>对话文件</h2>{files.length ? files.map((file) => <button className="file-link" key={file.url} onClick={() => openFile(file)}>{file.name}</button>) : <p>当前对话暂无已发布产物。运行完成后可从消息打开。</p>}</> : selection.kind === "file" ? <><h2>{selection.file.name}</h2><a href={selection.file.url} download>下载 {selection.file.name}</a><FileContent key={selection.file.url} api={api} file={selection.file} /></> : <><h2>{selection.title}</h2><div ref={setTarget} /></>}</div></aside>}</div></Context.Provider>;
}
export function EvidenceSurface({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const host = useFilePreview(); const id = useId(); const close = useRef(onClose); close.current = onClose;
  const open = host?.openEvidence, cleanup = host?.closeEvidence;
  useEffect(() => { open?.(id, title, () => close.current()); return () => cleanup?.(id); }, [open, cleanup, id, title]);
  if (!host) return <div className="evidence-preview" role="dialog" aria-label={title}>{children}</div>;
  return host.activeEvidence === id && host.target ? createPortal(children, host.target) : null;
}
export function FileButton({ file }: { file: Artifact }) { const host = useFilePreview(); return <button className="file-link" onClick={() => host?.openFile(file)}>打开 {file.name}</button>; }
