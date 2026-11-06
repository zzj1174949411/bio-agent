type Props = { status: string; bytesDownloaded: number; totalBytes: number | null; errorCode?: string | null; onCancel?: () => void };
const bytes = (value: number) => `${value.toLocaleString()} B`;

export function GeoImportProgress({ status, bytesDownloaded, totalBytes, errorCode, onCancel }: Props) {
  const terminal = status === "READY" || status === "FAILED" || status === "CANCELLED";
  const progress = totalBytes === null || totalBytes === 0 ? null : Math.min(100, Math.round((bytesDownloaded / totalBytes) * 100));
  return <section className="card geo-progress" aria-live="polite"><h3>GEO 导入</h3><p>状态：{status}</p>{status === "DOWNLOADING" && <><p>已下载 {bytes(bytesDownloaded)}{totalBytes === null ? "（总大小未知）" : ` / ${bytes(totalBytes)} (${progress}%)`}</p>{progress !== null && <progress value={bytesDownloaded} max={totalBytes ?? undefined} aria-label="下载进度" />}</>}{status === "CANCELLED" && <p>下载已取消</p>}{status === "FAILED" && <p role="alert">导入失败：{errorCode ?? "GEO_IMPORT_FAILED"}</p>}{status === "READY" && <p>文件已验证，等待样本映射。</p>}{!terminal && onCancel && <button type="button" onClick={onCancel}>取消下载</button>}</section>;
}
