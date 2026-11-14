import { MapPin, X } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";

/** A selection is one removable attachment; no separate map controls live in chat. */
export function CopilotContextPanel() {
  const context = useAnalysisStore((s) => s.copilotContext);
  const remove = useAnalysisStore((s) => s.removeCopilotContext);
  if (!context) return null;
  const period = context.start === context.end ? context.start
    : context.start.slice(0, 4) === context.end.slice(0, 4) && context.start.endsWith("01-01") && context.end.endsWith("12-31")
      ? `${context.start.slice(0, 4)} · full year` : `${context.start} – ${context.end}`;
  return <div role="status" aria-label="Added map context" className="mb-2 flex items-start gap-2 rounded-lg border border-reference/20 bg-reference/5 px-3 py-2 text-xs">
    <MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-reference" />
    <div className="min-w-0 flex-1">
      <p className="font-medium text-ink">Area and {context.start === context.end ? "day" : "period"} added as context</p>
      <p className="mt-0.5 break-words text-[11px] text-muted">{context.label} · {period}</p>
    </div>
    <button type="button" aria-label="Remove map context" title="Remove context" onClick={remove}
      className="rounded p-1 text-muted hover:bg-paper hover:text-ink focus-visible:outline-2 focus-visible:outline-reference"><X className="h-3.5 w-3.5" /></button>
  </div>;
}
