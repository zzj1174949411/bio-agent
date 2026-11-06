import { useState } from "react";

export function ClarificationCard({ requestId, revision, question, onRespond, disabled = false }: { requestId: string; revision: number; question: string; onRespond: (requestId: string, revision: number, value: string) => void; disabled?: boolean }) {
  const [value, setValue] = useState("");
  return <section className="card clarification"><h3>需要澄清</h3><p>{question}</p><small>revision {revision}</small><label>回答<textarea aria-label="澄清回答" value={value} disabled={disabled} onChange={(event) => setValue(event.target.value)} /></label><button type="button" disabled={disabled || !value.trim()} onClick={() => { onRespond(requestId, revision, value.trim()); setValue(""); }}>提交澄清</button></section>;
}
