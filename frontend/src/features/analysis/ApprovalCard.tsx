import { useState } from "react";
export function ApprovalCard({ revision, plan, busy = false, onApprove, onReject }: { revision: number; plan?: Record<string, unknown>; busy?: boolean; onApprove: (revision: number) => void; onReject?: () => void }) {
  const [confirmed, setConfirmed] = useState(false);
  const comparison = plan?.comparison as { factor?: string; numerator?: string; denominator?: string } | undefined;
  return <section className="card approval"><h3>分析计划</h3><p>当前 revision {revision}，请确认比较方向和参数。</p>{comparison && <p>{comparison.numerator} 相对 {comparison.denominator} · 分组列 {comparison.factor}</p>}{plan && <details><summary>查看本次完整方案</summary><pre>{JSON.stringify(plan, null, 2)}</pre></details>}<label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />我已核对本次方案</label><div><button type="button" disabled={!confirmed || busy} onClick={() => onApprove(revision)}>批准分析</button>{onReject && <button type="button" disabled={busy} onClick={onReject}>拒绝</button>}</div></section>;
}
