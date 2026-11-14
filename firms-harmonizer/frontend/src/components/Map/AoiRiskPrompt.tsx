import { useEffect, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { X, Zap } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";

export function AoiRiskPrompt({ onView }: { onView: () => void }) {
  const popup = useAnalysisStore((s) => s.aoiPromptPopup);
  const dismiss = useAnalysisStore((s) => s.dismissAoiPrompt);
  const panel = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const node = panel.current;
    if (!popup || !node) return;
    const place = () => {
      const { width, height } = node.getBoundingClientRect();
      const anchorX = popup.x + 14;
      const left = anchorX + width + 8 <= window.innerWidth ? anchorX : popup.x - width - 14;
      node.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, left))}px`;
      node.style.top = `${Math.max(8, Math.min(window.innerHeight - height - 8, popup.y - 12))}px`;
    };
    place();
    const animation = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? null
      : node.animate([{ opacity: 0, scale: 0.96 }, { opacity: 1, scale: 1 }],
        { duration: 150, easing: "cubic-bezier(0.2, 0.75, 0.25, 1)" });
    window.addEventListener("resize", place);
    return () => { animation?.cancel(); window.removeEventListener("resize", place); };
  }, [popup]);

  useEffect(() => {
    if (!popup) return;
    const timer = window.setTimeout(dismiss, 7000);
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") dismiss(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, [dismiss, popup]);

  if (!popup) return null;
  return createPortal(
    <div ref={panel} role="region" aria-label="Area risk prompt"
      className="fixed z-[60] w-max max-w-[calc(100vw-16px)] rounded-xl border border-slate-600/60 bg-slate-950/90 p-3 text-slate-50 shadow-xl backdrop-blur-md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0" role="status">
          <p className="text-xs font-semibold">Area selected · Run AI Fire Risk Prediction?</p>
          <p className="mt-0.5 truncate text-xs text-slate-300">{popup.aoiLabel}</p>
        </div>
        <button type="button" aria-label="Dismiss area risk prompt" onClick={dismiss}
          className="-mr-1 -mt-1 grid size-7 shrink-0 place-items-center rounded text-slate-300 hover:bg-white/10 focus-visible:outline-2">
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
      <button type="button" onClick={onView}
        className="mt-2 inline-flex min-h-8 items-center gap-1.5 rounded bg-sky-200 px-2.5 text-xs font-semibold text-slate-950 hover:bg-sky-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-200">
        <Zap className="size-3.5" aria-hidden="true" /> View Risk Prediction
      </button>
    </div>, document.body,
  );
}
