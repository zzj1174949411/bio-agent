import { useMemo, useState } from "react";
import type { ToolApprovalRequest } from "../../api/types";

export function ToolApprovalCard({ request, onDecide, disabled = false }: { request: ToolApprovalRequest; onDecide: (id: string, decision: "approve" | "deny", capabilityRevision: string, argumentsHash: string) => void; disabled?: boolean }) {
  const [decided, setDecided] = useState(false);
  const expired = useMemo(() => Date.parse(request.expiresAt) <= Date.now(), [request.expiresAt]);
  const stale = Boolean(request.currentCapabilityRevision && request.currentCapabilityRevision !== request.capabilityRevision);
  const blocked = disabled || decided || expired || stale;
  const decide = (decision: "approve" | "deny") => { if (blocked) return; setDecided(true); onDecide(request.id, decision, request.capabilityRevision, request.argumentsHash); };
  return <section className="card tool-approval" aria-label="工具调用确认"><h3>确认工具调用</h3><p><strong>{request.tool}</strong></p><p>目标：<code>{request.target}</code></p><details><summary>规范化参数</summary><pre>{JSON.stringify(request.arguments, null, 2)}</pre></details><small>capability revision：{request.capabilityRevision}</small><small>参数 hash：{request.argumentsHash}</small><small>过期时间：{request.expiresAt}</small>{expired && <p className="warning">该批准已过期。</p>}{stale && <p className="warning">工具能力已变化，旧批准不能使用。</p>}{request.errorCode && <p className="warning">工具状态：{request.errorCode}</p>}{request.result !== undefined && <details><summary>原始工具结果（不可信文本）</summary><pre>{typeof request.result === "string" ? request.result : JSON.stringify(request.result, null, 2)}</pre></details>}<div className="button-row"><button type="button" disabled={blocked} onClick={() => decide("approve")}>批准工具调用</button><button type="button" disabled={blocked} onClick={() => decide("deny")}>拒绝</button></div></section>;
}
