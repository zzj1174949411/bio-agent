import type { GeoSearchState } from "../../api/types";

type Props = {
  search: GeoSearchState;
  onSelect: (accession: string, revision: number) => void;
  onNext: (pageToken: string, revision: number) => void;
  onCancel: () => void;
  onRetry: () => void;
};

const filterText = (label: string, value: string | null) => value ? `${label}：${value}` : null;

export function GeoSearchResults({ search, onSelect, onNext, onCancel, onRetry }: Props) {
  const active = ["QUEUED", "SEARCHING", "AWAITING_SELECTION"].includes(search.status);
  return <section className="card geo-search" aria-label="GEO 搜索结果">
    <h3>GEO 关键词搜索</h3>
    <p><strong>{search.query.text}</strong></p>
    {[filterText("物种", search.query.organism), filterText("组织", search.query.tissue), filterText("技术", search.query.technology)].filter((value): value is string => value !== null).map((value) => <p className="hint" key={value}>{value}</p>)}
    {search.status === "FAILED" && <><p role="alert">{search.error_code ?? "GEO_SEARCH_FAILED"}</p><button type="button" onClick={onRetry}>重试搜索</button></>}
    {["QUEUED", "SEARCHING"].includes(search.status) && <p role="status">正在搜索 GEO…</p>}
    {search.status === "SELECTED" && <p role="status">已选择数据集，正在检查可分析文件。</p>}
    {search.status === "CANCELLED" && <p role="status">GEO 搜索已取消。</p>}
    {search.status === "AWAITING_SELECTION" && <><p className="hint">检索到 {search.result_count} / {search.total} 个候选；结果还需检查 raw counts，尚不能立即分析。</p><ul className="geo-search-hits">{search.items.map((hit) => <li key={hit.source_id}><strong>{hit.source_id}</strong><span aria-hidden="true"> · </span><span>{hit.title}</span>{hit.summary && <p>{hit.summary}</p>}<small>{hit.organisms.join("；") || "物种未提供"} · {hit.platforms.join("；") || "平台未提供"} · {hit.sample_count === null ? "样本数未提供" : `${hit.sample_count} 个样本`}</small><p className="hint">{hit.analysis_readiness === "NEEDS_INSPECTION" ? "还需检查 raw counts 与样本信息。" : hit.analysis_readiness}</p><a href={hit.source_uri} target="_blank" rel="noreferrer">查看官方记录</a><button type="button" onClick={() => onSelect(hit.source_id, search.revision)}>检查 {hit.source_id} 的可分析文件</button></li>)}</ul>{search.next_page_token && <button type="button" onClick={() => onNext(search.next_page_token as string, search.revision)}>下一页</button>}</>}
    {active && <button type="button" onClick={onCancel}>取消搜索</button>}
  </section>;
}
