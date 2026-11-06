export type WorkbenchEvent = { seq: number; kind: string; payload: Record<string, unknown> };

export function appendEvent(items: WorkbenchEvent[], event: WorkbenchEvent): WorkbenchEvent[] {
  if (items.some((item) => item.seq === event.seq)) return items;
  return [...items, event].sort((left, right) => left.seq - right.seq);
}

export function parseEventBlock(block: string): WorkbenchEvent | null {
  const id = block.match(/^id: (\d+)$/m)?.[1];
  const kind = block.match(/^event: ([\w.]+)$/m)?.[1];
  const data = block.match(/^data: (.+)$/m)?.[1];
  if (!id || !kind || !data) return null;
  return { seq: Number(id), kind, payload: JSON.parse(data) as Record<string, unknown> };
}
