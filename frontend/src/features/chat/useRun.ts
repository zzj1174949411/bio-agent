import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClient } from "../../api/client";
import type { Artifact, RunSummary } from "../../api/types";

export type RunPlan = { run_id: string; plan_revision: number; plan: Record<string, unknown> };
export function useRun(api: ApiClient, runId: string | null) {
  const [run, setRun] = useState<RunSummary | null>(null); const [plan, setPlan] = useState<RunPlan | null>(null); const [files, setFiles] = useState<Artifact[]>([]);
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false); const generation = useRef(0); const refresh = useRef<() => Promise<void>>(async () => {});
  useEffect(() => { const version = ++generation.current; let loading = false;
    setRun(null); setPlan(null); setFiles([]); setError(""); setBusy(false);
    const load = async () => { if (!runId || loading) return; loading = true;
      try { const value = await api.run(runId); if (generation.current !== version) return;
        const current = { status: String(value.status ?? ""), qc_status: typeof value.qc_status === "string" ? value.qc_status : null };
        setRun(current);
        if (current.status === "AWAITING_APPROVAL") { const next = await api.runPlan(runId); if (generation.current === version) setPlan(next); }
        else setPlan(null);
        if (current.status === "COMPLETED") { const result = await api.artifacts(runId); if (generation.current !== version) return;
          setFiles(result.artifacts.map((file) => ({ ...file, name: file.name ?? file.artifact_id, url: api.artifactUrl(runId, file.artifact_id) })));
        }
      } catch { if (generation.current === version) setError("无法核验运行或产物，请检查连接后重试。"); }
      finally { loading = false; }
    };
    refresh.current = load; void load(); const timer = setInterval(() => void load(), 1500);
    return () => { generation.current++; clearInterval(timer); };
  }, [api, runId]);
  const approve = useCallback(async (revision: number) => { if (!runId || busy) return; const version = generation.current; setBusy(true); setError("");
    try { await api.approveRun(runId, revision); if (generation.current !== version) return; setPlan(null); setRun({ status: "QUEUED" }); await refresh.current(); }
    catch { if (generation.current === version) setError("批准失败或方案已变化，请重新核验当前方案。"); }
    finally { if (generation.current === version) setBusy(false); }
  }, [api, runId, busy]);
  const cancel = useCallback(async () => { if (!runId || busy) return; const version = generation.current; setBusy(true);
    try { await api.cancelRun(runId); if (generation.current !== version) return; setRun({ status: "CANCELLED" }); setPlan(null); await refresh.current(); }
    catch { if (generation.current === version) setError("取消运行失败，请检查连接并重试。"); }
    finally { if (generation.current === version) setBusy(false); }
  }, [api, runId, busy]);
  return { run, plan, files, error, busy, approve, cancel };
}
