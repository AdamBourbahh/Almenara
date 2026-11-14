import type { ReactNode } from "react";

export interface SegmentOption<T extends string> {
  value: T;
  label: string;
  hint?: string;
  icon?: ReactNode;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = "md",
}: {
  options: ReadonlyArray<SegmentOption<T>>;
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  size?: "sm" | "md";
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="inline-flex rounded-xl border border-line bg-base/60 p-1"
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            role="tab"
            aria-selected={active}
            type="button"
            onClick={() => onChange(option.value)}
            className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-left transition-colors duration-200 ${
              active
                ? "bg-white/[0.07] text-ink ring-1 ring-white/10"
                : "text-dim hover:bg-white/[0.03] hover:text-ink"
            } ${size === "sm" ? "text-xs" : "text-sm"}`}
          >
            {option.icon && (
              <span className={active ? "text-ember" : "text-dim"}>
                {option.icon}
              </span>
            )}
            <span className="flex flex-col">
              <span className="font-medium">{option.label}</span>
              {option.hint && (
                <span className="text-[10px] font-normal text-dim">
                  {option.hint}
                </span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
