import type { GeoSample } from "../../api/types";

type Props = { samples: GeoSample[]; selected: string[]; groups: Record<string, string>; numerator: string; denominator: string; onGroup: (sample: string, group: string) => void; onNumerator: (value: string) => void; onDenominator: (value: string) => void };

export function GroupSelection({ samples, selected, groups, numerator, denominator, onGroup, onNumerator, onDenominator }: Props) {
  const included = samples.filter((sample) => selected.includes(sample.accession));
  const levels = [...new Set(included.map((sample) => groups[sample.accession]?.trim()).filter((value): value is string => Boolean(value)))];
  return <fieldset className="geo-groups"><legend>分组与比较</legend>{included.map((sample) => <label key={sample.accession}>{sample.accession} 分组<input aria-label={`${sample.accession} 分组`} value={groups[sample.accession] ?? ""} onChange={(event) => onGroup(sample.accession, event.target.value)} />{sample.characteristics && <small>{sample.characteristics.map((field) => `${field.name}: ${field.value}`).join("；")}</small>}</label>)}<div className="geo-direction"><label>numerator<select aria-label="numerator" value={numerator} onChange={(event) => onNumerator(event.target.value)}>{levels.map((level) => <option key={level}>{level}</option>)}</select></label><label>denominator<select aria-label="denominator" value={denominator} onChange={(event) => onDenominator(event.target.value)}>{levels.map((level) => <option key={level}>{level}</option>)}</select></label></div></fieldset>;
}
