import type { HTMLAttributes, ReactNode } from "react";

export function Panel({
  className = "",
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-2xl border border-line bg-surface shadow-panel ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

export function PanelHeader({
  icon,
  title,
  subtitle,
  action,
}: {
  icon?: ReactNode;
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
      <div className="flex items-start gap-3">
        {icon && (
          <span className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-white/[0.04] text-ember">
            {icon}
          </span>
        )}
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-dim">{subtitle}</p>}
        </div>
      </div>
      {action}
    </header>
  );
}
