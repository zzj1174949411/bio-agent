import type { ReactNode } from "react";

function inline(source: string) {
  const result: ReactNode[] = []; const pattern = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g; let cursor = 0; let match: RegExpExecArray | null;
  while ((match = pattern.exec(source))) { if (match.index > cursor) result.push(<span key={`text-${cursor}`}>{source.slice(cursor, match.index)}</span>); result.push(<a key={`link-${match.index}`} href={match[2]} target="_blank" rel="noreferrer">{match[1]}</a>); cursor = match.index + match[0].length; }
  if (cursor < source.length) result.push(<span key={`text-${cursor}`}>{source.slice(cursor)}</span>); return result.length ? result : source;
}

export function SafeMarkdown({ source }: { source: string }) {
  return <div className="safe-markdown">{source.split("\n").map((line, index) => <p key={index}>{inline(line)}</p>)}</div>;
}
