import type { ReactNode } from "react";

export function InsightCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-ink">
        {icon}
        {title}
      </h3>
      <p className="mt-1.5 text-xs leading-relaxed text-dim">{children}</p>
    </div>
  );
}

export function MiniStat({
  label,
  value,
  tone = "text-ink",
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-[11px] font-medium text-dim">{label}</span>
      <span className={`font-tabular text-lg font-semibold tracking-tight ${tone}`}>
        {value}
      </span>
    </div>
  );
}
