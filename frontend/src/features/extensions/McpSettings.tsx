import { useEffect, useMemo, useState } from "react";
import type { McpServer, ToolDescriptor } from "../../api/types";
import { ToolPolicyEditor } from "./ToolPolicyEditor";

export type McpDraft = {
  serverId?: string; revision?: number; label: string; transport: "stdio" | "http";
  executable: string; argv: string[]; cwd: string; endpoint: string;
  credentialRef: string; credentialValue: string;
};

type Props = { servers: McpServer[]; tools?: ToolDescriptor[]; onSave: (draft: McpDraft) => void; onConnect: (serverId: string) => void; onDisconnect?: (serverId: string) => void; onPolicyChange?: (tool: ToolDescriptor, policy: ToolDescriptor["policy"]) => void };

export function McpSettings({ servers, tools = [], onSave, onConnect, onDisconnect, onPolicyChange }: Props) {
  const [selectedId, setSelectedId] = useState(""); const [label, setLabel] = useState(""); const [transport, setTransport] = useState<"stdio" | "http">("http"); const [executable, setExecutable] = useState(""); const [argvText, setArgvText] = useState(""); const [cwd, setCwd] = useState(""); const [endpoint, setEndpoint] = useState(""); const [credentialRef, setCredentialRef] = useState("default"); const [credentialValue, setCredentialValue] = useState("");
  const selected = servers.find((server) => server.id === selectedId);
  useEffect(() => {
    if (!selected) { if (selectedId) return; setLabel(""); setTransport("http"); setExecutable(""); setArgvText(""); setCwd(""); setEndpoint(""); setCredentialRef("default"); setCredentialValue(""); return; }
    setLabel(selected.label); setTransport(selected.transport); setExecutable(selected.stdio?.executable ?? ""); setArgvText(selected.stdio?.argv.join("\n") ?? ""); setCwd(selected.stdio?.cwd ?? ""); setEndpoint(selected.http?.endpoint ?? ""); setCredentialRef(Object.values(selected.stdio?.env_refs ?? selected.http?.header_refs ?? {})[0] ?? "default"); setCredentialValue("");
  }, [selected, selectedId]);
  const argv = useMemo(() => argvText.split(/\r?\n/).map((value) => value.trim()).filter(Boolean), [argvText]);
  const preview = useMemo(() => transport === "stdio" ? [executable || "<绝对程序路径>", ...argv.map((value) => JSON.stringify(value))].join(" ") : endpoint || "<HTTP endpoint>", [argv, endpoint, executable, transport]);
  const save = (editing: boolean) => { onSave({ ...(editing && selected ? { serverId: selected.id, revision: selected.revision } : {}), label, transport, executable, argv, cwd, endpoint, credentialRef, credentialValue }); setCredentialValue(""); };
  return <section className="card settings mcp-settings"><h2>MCP</h2><label>已保存 MCP 服务<select aria-label="已保存 MCP 服务" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}><option value="">新服务</option>{servers.map((server) => <option key={server.id} value={server.id}>{server.label}</option>)}</select></label><label>名称<input value={label} onChange={(event) => setLabel(event.target.value)} /></label><label>Transport<select aria-label="MCP transport" value={transport} onChange={(event) => setTransport(event.target.value as "stdio" | "http")}><option value="http">Streamable HTTP</option><option value="stdio">stdio</option></select></label>{transport === "stdio" ? <><label>绝对程序路径<input aria-label="绝对程序路径" value={executable} onChange={(event) => setExecutable(event.target.value)} /></label><label>参数 argv（每行一项）<textarea aria-label="参数 argv（每行一项）" value={argvText} onChange={(event) => setArgvText(event.target.value)} /></label><label>工作目录<input value={cwd} onChange={(event) => setCwd(event.target.value)} /></label></> : <label>Endpoint<input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} /></label>}<label>凭据引用<input aria-label="凭据引用" value={credentialRef} onChange={(event) => setCredentialRef(event.target.value)} /></label><label>凭据值<input aria-label="凭据值" type="password" autoComplete="off" value={credentialValue} onChange={(event) => setCredentialValue(event.target.value)} /></label><p className="hint">连接预览：<code>{preview}</code></p><div className="button-row"><button type="button" onClick={() => save(false)}>添加 MCP 服务</button><button type="button" onClick={() => save(Boolean(selected))}>保存 MCP 服务</button><button type="button" disabled={!selected} onClick={() => selected && onConnect(selected.id)}>连接</button><button type="button" disabled={!selected} onClick={() => selected && onDisconnect?.(selected.id)}>断开</button></div>{selected?.protocol_version && <p className="hint">协议：{selected.protocol_version}</p>}<ToolPolicyEditor tools={tools} onChange={(tool, policy) => onPolicyChange?.(tool, policy)} /></section>;
}
