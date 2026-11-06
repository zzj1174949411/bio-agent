import { useState, type KeyboardEvent } from "react";
import type { DatasetOption, ProfileOption } from "../../api/types";

type ComposerProps = { onSend: (text: string) => void; disabled?: boolean; sending?: boolean; datasets?: DatasetOption[]; selectedDatasetIds?: string[]; onDatasetChange?: (ids: string[]) => void; profiles?: ProfileOption[]; selectedProfileId?: string; onProfileChange?: (id: string) => void; onUpload?: (counts: File, metadata: File) => void };

export function Composer({ onSend, disabled = false, sending = false, datasets = [], selectedDatasetIds = [], onDatasetChange, profiles = [], selectedProfileId = "", onProfileChange, onUpload }: ComposerProps) {
  const [value, setValue] = useState("");
  const [counts, setCounts] = useState<File | null>(null); const [metadata, setMetadata] = useState<File | null>(null);
  const blocked = disabled || sending;
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault(); const text = value.trim(); if (!text || blocked) return;
    onSend(text); setValue("");
  };
  const toggleDataset = (id: string) => { const next = selectedDatasetIds.includes(id) ? selectedDatasetIds.filter((item) => item !== id) : [...selectedDatasetIds, id]; onDatasetChange?.(next); };
  const upload = () => { if (counts && metadata) { onUpload?.(counts, metadata); setCounts(null); setMetadata(null); } };
  return <div className="composer"><div className="composer-tools"><label>本轮模型<select aria-label="本轮模型" value={selectedProfileId} disabled={blocked} onChange={(event) => onProfileChange?.(event.target.value)}><option value="">默认模型</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}</option>)}</select></label><fieldset><legend>数据集</legend>{datasets.length === 0 ? <span className="hint">尚未选择数据集</span> : datasets.map((dataset) => <label key={dataset.id}><input type="checkbox" aria-label={`数据集 ${dataset.label}`} checked={selectedDatasetIds.includes(dataset.id)} disabled={blocked} onChange={() => toggleDataset(dataset.id)} />{dataset.label}</label>)}</fieldset><label>counts 文件<input aria-label="counts 文件" type="file" accept=".csv,.tsv" disabled={blocked} onChange={(event) => setCounts(event.target.files?.[0] ?? null)} /></label><label>metadata 文件<input aria-label="metadata 文件" type="file" accept=".csv,.tsv" disabled={blocked} onChange={(event) => setMetadata(event.target.files?.[0] ?? null)} /></label>{onUpload && <button type="button" disabled={blocked || !counts || !metadata} onClick={upload}>上传数据集</button>}</div><textarea aria-label="消息" value={value} disabled={blocked} onChange={(event) => setValue(event.target.value)} onKeyDown={onKeyDown} placeholder="输入消息，Enter 发送，Shift+Enter 换行" /><button type="button" disabled={blocked || !value.trim()} onClick={() => { const text=value.trim(); if(text){onSend(text);setValue("");} }}>发送</button></div>;
}
