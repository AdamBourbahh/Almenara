import type { ReactNode } from "react";

type Tone = "default" | "ember" | "danger" | "success" | "info";

const TONE: Record<Tone, string> = {
  default: "text-ink",
  ember: "text-ember",
  danger: "text-danger",
  success: "text-success",
  info: "text-info",
};

export function Stat({
  label,
  value,
  unit,
  hint,
  tone = "default",
  icon,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: Tone;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="flex items-center gap-1.5 text-[11px] font-medium text-dim">
        {icon}
        {label}
      </span>
      <span className={`font-tabular text-2xl font-semibold tracking-tight ${TONE[tone]}`}>
        {value}
        {unit && (
          <span className="ml-1 text-xs font-medium text-dim">{unit}</span>
        )}
      </span>
      {hint && <span className="text-[11px] leading-snug text-dim">{hint}</span>}
    </div>
  );
}
