import type { Message } from "../../api/types";
import { SafeMarkdown } from "../../components/SafeMarkdown";

export function ChatTimeline({ messages }: { messages: Message[] }) {
  return <div className="timeline" aria-live="polite">{messages.length === 0 ? <p className="empty">开始一段可审计的分析对话</p> : messages.map((message) => <article className={`message ${message.role}`} key={message.id}><small>{message.role === "user" ? "你" : "Bio-Agent"}</small><SafeMarkdown source={message.content} />{message.partial && <span className="partial">生成中…</span>}</article>)}</div>;
}
