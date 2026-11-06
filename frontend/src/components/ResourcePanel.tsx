import type { Artifact, RunSummary } from "../api/types";

type ResourcePanelProps = { run?: RunSummary | null; plots?: Array<{ name: string; url: string }>; artifacts?: Artifact[] };

export function ResourcePanel({ run, plots = [], artifacts = [] }: ResourcePanelProps) {
  const qc = run?.qcStatus ?? run?.qc_status;
  const report = run?.reportUrl ?? run?.report_url;
  const plotItems = plots.length ? plots : run?.plots ?? []; const artifactItems = artifacts.length ? artifacts : run?.artifacts ?? [];
  return <aside className="resources"><h2>资源与结果</h2>{!run ? <p>选择一个对话查看数据集、QC 和报告。</p> : <><p>运行状态：{run.status}</p>{qc && <p>QC: {qc}</p>}{plotItems.length > 0 && <section><h3>图表</h3>{plotItems.map((plot) => <figure key={plot.url}><img src={plot.url} alt={plot.name} /><figcaption>{plot.name}</figcaption></figure>)}</section>}{report && <div className="report-frame" aria-label="沙箱报告"><iframe title="报告预览" src={report} sandbox="" /></div>}{artifactItems.length > 0 && <section><h3>下载</h3>{artifactItems.map((artifact) => <a key={artifact.url} href={artifact.url} download>{`下载 ${artifact.name}`}</a>)}</section>}</>}</aside>;
}
