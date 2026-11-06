import { useEffect, useState } from "react";
import type { ModelProfile } from "../../api/types";

export type ModelPayload = { label: string; provider: string; model: string; baseUrl: string; apiKey: string };
type Action = void | Promise<void>;
type Props = {
  onSave: (payload: ModelPayload) => Action;
  profiles?: ModelProfile[];
  selectedProfileId?: string;
  onSelectProfile?: (id: string) => void;
  onUpdate?: (id: string, revision: number, payload: ModelPayload) => Action;
  onDelete?: (id: string, revision: number) => Action;
  onClearCredential?: (id: string) => Action;
  onProbe?: (id: string) => Action;
};

export function ModelSettings({ onSave, profiles = [], selectedProfileId = "", onSelectProfile, onUpdate, onDelete, onClearCredential, onProbe }: Props) {
  const [label, setLabel] = useState("本地模型");
  const [provider, setProvider] = useState("deepseek");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selected = profiles.find((profile) => profile.id === selectedProfileId);
  const readOnly = Boolean(selected?.read_only);
  useEffect(() => {
    setLabel(selected?.label ?? "本地模型"); setProvider(selected?.provider ?? "deepseek");
    setModel(selected?.model ?? ""); setBaseUrl(selected?.base_url ?? ""); setApiKey(""); setError("");
  }, [selected]);
  const perform = async (action: () => Action) => {
    if (busy) return;
    setBusy(true); setError("");
    try { await action(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "操作失败，请检查配置后重试。"); }
    finally { setApiKey(""); setBusy(false); }
  };
  const save = () => {
    const payload = { label, provider, model, baseUrl, apiKey };
    setApiKey("");
    void perform(() => selected && selected.revision ? onUpdate?.(selected.id, selected.revision, payload) : onSave(payload));
  };
  return <section className="card settings" aria-label="模型与 API 配置">
    <h2>模型与 API</h2>
    <label>已保存模型<select aria-label="已保存模型" disabled={busy} value={selectedProfileId} onChange={(event) => onSelectProfile?.(event.target.value)}>
      <option value="">新模型</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.label}{profile.read_only ? "（可选环境配置，只读）" : ""}</option>)}
    </select></label>
    <label>名称<input disabled={readOnly || busy} value={label} onChange={(event) => setLabel(event.target.value)} /></label>
    <label>接口协议<select disabled={readOnly || busy} value={provider} onChange={(event) => setProvider(event.target.value)}>
      <option value="openai_compatible">OpenAI 兼容 Chat Completions</option><option value="deepseek">DeepSeek</option><option value="ollama">Ollama</option>
    </select></label>
    <label>模型 ID<input aria-label="模型" disabled={readOnly || busy} value={model} placeholder={provider === "deepseek" ? "deepseek-chat" : provider === "ollama" ? "qwen3:8b" : "服务商提供的模型 ID"} onChange={(event) => setModel(event.target.value)} /></label>
    <label>API Base URL<input disabled={readOnly || busy} value={baseUrl} placeholder={provider === "deepseek" ? "https://api.deepseek.com" : provider === "ollama" ? "http://localhost:11434" : "https://your-provider.example/v1"} onChange={(event) => setBaseUrl(event.target.value)} /></label>
    <label>API Key<input aria-label="API Key" disabled={readOnly || busy || provider === "ollama"} type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off" /></label>
    <p className="hint">{provider === "ollama" ? "Ollama 不需要 API Key，请先在本机启动服务并安装模型。" : selected?.credential_configured ? "凭据已保存在系统凭据库；留空保留现有 Key。" : "请输入服务商的 API Key，密钥只发送至后端系统凭据库。"}</p>
    <div className="button-row">
      {readOnly ? <button type="button" disabled>环境配置只读</button> : <button type="button" disabled={busy} onClick={save}>{selected ? "更新模型" : "保存模型"}</button>}
      {selected && <><button type="button" disabled={busy} onClick={() => void perform(() => onProbe?.(selected.id))}>探测连接</button>{!readOnly && <>
        <button type="button" disabled={busy} onClick={() => void perform(() => onClearCredential?.(selected.id))}>清除凭据</button>
        <button type="button" disabled={busy} onClick={() => void perform(() => selected.revision ? onDelete?.(selected.id, selected.revision) : undefined)}>删除模型</button>
      </>}</>}
    </div>
    {busy && <p role="status">正在提交，请稍候…</p>}{error && <p className="error" role="alert">{error}</p>}
    {readOnly ? <p className="hint">可选兼容配置：BIOAGENT_DEEPSEEK_API_KEY 等环境变量由服务启动时读取。正常使用请选择“新模型”在页面保存，无需 .env 或重启。</p> : <p className="hint">编辑配置不改变聊天选择；保存后无需重启，在聊天输入区选择模型。连接探针只验证固定请求的结构化输出，不代表所有工具能力均可用。</p>}
  </section>;
}
