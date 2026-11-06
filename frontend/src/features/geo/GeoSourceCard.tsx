import { useState } from "react";
import type { GeoCandidate } from "../../api/types";

type Props = {
  candidates: GeoCandidate[];
  onConfirm: (candidateId: string, confirmedUnknown: boolean) => void;
  accession?: string;
  title?: string | null;
  organisms?: string[];
  platforms?: string[];
  officialUrl?: string;
  maxBytes?: number;
  disabled?: boolean;
};

const byteText = (value: number | null) => value === null ? "大小未知" : `${value.toLocaleString()} B`;

export function GeoSourceCard({ candidates, onConfirm, accession, title, organisms = [], platforms = [], officialUrl, maxBytes = 100 * 1024 * 1024, disabled = false }: Props) {
  const [confirmedUnknown, setConfirmedUnknown] = useState<Record<string, boolean>>({});
  const importable = candidates.filter((candidate) => candidate.data_kind === "RAW_COUNTS" || candidate.data_kind === "UNKNOWN");
  const recordUrl = officialUrl ?? (accession ? `https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${encodeURIComponent(accession)}` : undefined);
  return <section className="card geo-source" aria-label="GEO 来源候选"><h3>GEO 来源</h3>{accession && <p><strong>{accession}</strong>{title ? ` · ${title}` : ""}</p>}{organisms.length > 0 && <p>物种：{organisms.join("；")}</p>}{platforms.length > 0 && <p>平台：{platforms.join("；")}</p>}{maxBytes !== undefined && <p className="hint">下载上限 {maxBytes.toLocaleString()} B</p>}{recordUrl && <a href={recordUrl} target="_blank" rel="noreferrer">查看官方记录</a>}{importable.length === 0 && <p role="status">没有可下载的原始 counts 候选文件。</p>}<ul className="geo-candidates">{candidates.map((candidate) => { const requiresConfirmation = candidate.data_kind === "UNKNOWN"; const unavailable = candidate.data_kind === "NORMALIZED" || candidate.data_kind === "UNSUPPORTED"; const canDownload = !disabled && !unavailable && (!requiresConfirmation || confirmedUnknown[candidate.id]); return <li key={candidate.id}><strong>{candidate.file_name}</strong><span>{candidate.data_kind} · {byteText(candidate.size_bytes)}</span><small>{candidate.evidence.join("；")}</small>{requiresConfirmation && <label><input type="checkbox" aria-label={`确认 ${candidate.file_name} 是原始 counts`} checked={Boolean(confirmedUnknown[candidate.id])} disabled={disabled} onChange={(event) => setConfirmedUnknown((current) => ({ ...current, [candidate.id]: event.target.checked }))} />我确认这是未标准化的整数 raw counts</label>}{unavailable && <small className="warning">该文件不是可用于 DESeq2 的原始 counts。</small>}<button type="button" disabled={!canDownload} onClick={() => onConfirm(candidate.id, requiresConfirmation)}>下载 {candidate.file_name}</button></li>; })}</ul></section>;
}
