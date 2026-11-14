import type { ReactNode } from "react";
import {
  Activity,
  CalendarDays,
  Circle,
  Flame,
  Map as MapIcon,
  ShieldCheck,
} from "lucide-react";

export type ViewKey = "map" | "history" | "trends" | "validation";

const NAV: Array<{
  key: ViewKey;
  label: string;
  hint: string;
  icon: ReactNode;
}> = [
  {
    key: "map",
    label: "Map",
    hint: "Explore fire activity",
    icon: <MapIcon className="h-[18px] w-[18px]" />,
  },
  {
    key: "history",
    label: "History",
    hint: "26-year calendar",
    icon: <CalendarDays className="h-[18px] w-[18px]" />,
  },
  {
    key: "trends",
    label: "Trends",
    hint: "Season clock & forecast",
    icon: <Activity className="h-[18px] w-[18px]" />,
  },
  {
    key: "validation",
    label: "Validation",
    hint: "How the data is proven",
    icon: <ShieldCheck className="h-[18px] w-[18px]" />,
  },
];

export function Sidebar({
  active,
  onChange,
}: {
  active: ViewKey;
  onChange: (key: ViewKey) => void;
}) {
  return (
    <aside className="hidden w-[236px] shrink-0 flex-col border-r border-line bg-surface/50 md:flex">
      <div className="flex items-center gap-3 px-5 pb-5 pt-6">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-ember/15 ring-1 ring-ember/30">
          <Flame className="h-5 w-5 text-ember" />
        </div>
        <div>
          <p className="text-sm font-semibold tracking-tight text-ink">
            FIRMS Harmonizer
          </p>
          <p className="text-[11px] text-dim">MODIS + VIIRS</p>
        </div>
      </div>

      <nav className="flex flex-col gap-1 px-3" aria-label="Primary">
        {NAV.map((item) => {
          const isActive = item.key === active;
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => onChange(item.key)}
              aria-current={isActive ? "page" : undefined}
              className={`group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors duration-200 ${
                isActive
                  ? "bg-white/[0.06] text-ink"
                  : "text-dim hover:bg-white/[0.03] hover:text-ink"
              }`}
            >
              <span
                className={
                  isActive ? "text-ember" : "text-dim group-hover:text-ink"
                }
              >
                {item.icon}
              </span>
              <span className="flex flex-col">
                <span className="text-sm font-medium">{item.label}</span>
                <span className="text-[11px] text-dim">{item.hint}</span>
              </span>
              {isActive && (
                <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-ember" />
              )}
            </button>
          );
        })}
      </nav>

      <div className="mt-auto px-5 py-5">
        <div className="rounded-xl border border-line bg-black/20 p-3">
          <p className="flex items-center gap-2 text-[11px] font-medium text-dim">
            <Circle className="h-2 w-2 fill-success text-success" />
            Offline-ready
          </p>
          <p className="mt-1 text-[10px] leading-relaxed text-dim">
            Runs on a laptop without internet. Missing data falls back to a
            deterministic fixture automatically.
          </p>
        </div>
        <p className="mt-3 font-mono text-[10px] text-dim">
          NASA Space Apps 2026
        </p>
      </div>
    </aside>
  );
}
