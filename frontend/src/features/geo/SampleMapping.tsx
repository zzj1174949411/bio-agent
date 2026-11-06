import { useEffect, useMemo, useRef, useState } from "react";
import type { GeoImportState, GeoSelection, GeoSource } from "../../api/types";
import { GroupSelection } from "./GroupSelection";

type Props = { source: Pick<GeoSource, "id" | "accession" | "samples">; imported: GeoImportState; onSubmit: (selection: GeoSelection) => void; onBack: () => void; errorCode?: string | null; confirmedRawType?: boolean; requiresRawConfirmation?: boolean };

function initialGroups(source: Props["source"]) {
  return Object.fromEntries(source.samples.map((sample) => [sample.accession, sample.characteristics?.[0]?.value ?? ""]));
}

function initialMap(imported: GeoImportState) {
  return { ...(imported.preview?.suggested_sample_map ?? {}) };
}

export function SampleMapping({ source, imported, onSubmit, onBack, errorCode, confirmedRawType = false, requiresRawConfirmation = false }: Props) {
  const preview = imported.preview;
  const previewKey = `${imported.revision}:${imported.raw_sha256 ?? ""}`;
  const previousKey = useRef(previewKey);
  const [sampleMap, setSampleMap] = useState<Record<string, string>>(() => initialMap(imported));
  const [groups, setGroups] = useState<Record<string, string>>(() => initialGroups(source));
  const [numerator, setNumerator] = useState("AD");
  const [denominator, setDenominator] = useState("Control");
  const [reconfirmed, setReconfirmed] = useState(false);
  const [confirmedRaw, setConfirmedRaw] = useState(confirmedRawType);
  const [sourceChanged, setSourceChanged] = useState(false);

  useEffect(() => {
    if (previousKey.current === previewKey) return;
    previousKey.current = previewKey;
    setSourceChanged(true);
    setReconfirmed(false);
    setConfirmedRaw(false);
    setSampleMap(initialMap(imported));
    setGroups(initialGroups(source));
  }, [imported, previewKey, source]);

  const mappedEntries = useMemo(() => (preview?.sample_columns ?? []).map((column) => [column, sampleMap[column] ?? ""] as const).filter((entry) => entry[1]), [preview?.sample_columns, sampleMap]);
  const mappedSamples = mappedEntries.map(([, sample]) => sample);
  const duplicates = mappedSamples.filter((sample, index) => mappedSamples.indexOf(sample) !== index);
  const excluded = source.samples.map((sample) => sample.accession).filter((sample) => !mappedSamples.includes(sample));
  const levels = [...new Set(mappedSamples.map((sample) => groups[sample]?.trim()).filter((value): value is string => Boolean(value)))];
  const counts = Object.fromEntries(levels.map((level) => [level, mappedSamples.filter((sample) => groups[sample]?.trim() === level).length]));
  const mappingComplete = mappedEntries.length > 0 && mappedEntries.length === (preview?.sample_columns.length ?? 0) && duplicates.length === 0;
  const groupsValid = levels.length === 2 && numerator !== denominator && levels.includes(numerator) && levels.includes(denominator) && (counts[numerator] ?? 0) >= 2 && (counts[denominator] ?? 0) >= 2;
  const validationMessage = sourceChanged && !reconfirmed ? "来源文件或 revision 已更新，请重新确认映射" : duplicates.length ? "每个 GSM 只能映射一次" : !mappingComplete ? "请为每个矩阵样本列映射 GSM" : levels.length !== 2 ? "请选择恰好两个分组" : numerator === denominator ? "比较方向的两个组必须不同" : (counts[numerator] ?? 0) < 2 || (counts[denominator] ?? 0) < 2 ? "每组至少需要 2 个样本" : null;
  const canSubmit = Boolean(preview && imported.raw_sha256 && validationMessage === null && groupsValid && (!requiresRawConfirmation || confirmedRaw));

  const rawSha256 = imported.raw_sha256;
  if (!preview || !rawSha256) return <section className="card"><p role="alert">尚未获得可确认的样本映射预览。</p></section>;
  const submit = () => {
    if (!canSubmit) return;
    const selection: GeoSelection = { source_id: source.id, candidate_id: imported.candidate_id, raw_sha256: rawSha256, feature_column: preview.feature_columns[0] ?? "feature_id", sample_columns: mappedEntries.map(([column]) => column), sample_map: Object.fromEntries(mappedEntries), groups: Object.fromEntries(mappedSamples.map((sample) => [sample, groups[sample].trim()])), group_factor: "condition", numerator, denominator, revision: imported.revision, ...(requiresRawConfirmation ? { confirmed_raw_type: "RAW_COUNTS" as const } : {}), excluded_samples: excluded, evidence: ["用户已确认矩阵列、GSM 映射和比较分组"] };
    onSubmit(selection);
  };
  return <section className="card geo-mapping"><h3>样本映射</h3><p>{source.accession}：矩阵列 → GSM → 原始 characteristics → 分组</p>{errorCode && <p role="alert">{errorCode}</p>}{sourceChanged && <label><input type="checkbox" aria-label="重新确认当前来源文件" checked={reconfirmed} onChange={(event) => setReconfirmed(event.target.checked)} />我已重新确认当前来源文件与样本映射</label>}{requiresRawConfirmation && <label><input type="checkbox" aria-label="确认当前文件是原始 counts" checked={confirmedRaw} onChange={(event) => setConfirmedRaw(event.target.checked)} />我确认当前文件是未标准化的整数 raw counts</label>}<div className="mapping-table" role="table" aria-label="矩阵样本映射">{preview.sample_columns.map((column) => { const gsm = sampleMap[column] ?? ""; const sample = source.samples.find((item) => item.accession === gsm); return <div role="row" key={column}><strong role="cell">{column}</strong><label role="cell">GSM<select aria-label={`矩阵列 ${column} 对应 GSM`} value={gsm} onChange={(event) => setSampleMap((current) => ({ ...current, [column]: event.target.value }))}><option value="">未映射</option>{source.samples.map((item) => <option key={item.accession} value={item.accession}>{item.accession}</option>)}</select></label><span role="cell">{sample?.characteristics?.map((field) => `${field.name}: ${field.value}`).join("；") ?? "未映射"}</span></div>; })}</div>{excluded.length > 0 && <p className="hint">排除样本：{excluded.join("、")}</p>}<GroupSelection samples={source.samples} selected={mappedSamples} groups={groups} numerator={numerator} denominator={denominator} onGroup={(sample, group) => setGroups((current) => ({ ...current, [sample]: group }))} onNumerator={setNumerator} onDenominator={setDenominator} />{levels.length === 2 && <p>比较方向：{numerator} 相对 {denominator}；{numerator} {counts[numerator] ?? 0} 个，{denominator} {counts[denominator] ?? 0} 个。</p>}{validationMessage && <p role="alert">{validationMessage}</p>}<div className="button-row"><button type="button" onClick={submit} disabled={!canSubmit}>确认样本映射</button><button type="button" onClick={onBack}>返回候选文件</button></div></section>;
}
