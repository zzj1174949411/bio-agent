export function ApprovalCard({ revision, onApprove, onReject }: { revision: number; onApprove: (revision: number) => void; onReject?: () => void }) {
  return <section className="card approval"><h3>分析计划</h3><p>当前 revision {revision}，请确认比较方向和参数。</p><div><button type="button" onClick={() => onApprove(revision)}>批准分析</button>{onReject && <button type="button" onClick={onReject}>拒绝</button>}</div></section>;
}
