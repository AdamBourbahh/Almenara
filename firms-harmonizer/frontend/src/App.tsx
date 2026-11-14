import { useEffect, useRef, useState } from "react";
import { Activity, CalendarDays, Gauge, Map as MapIcon, Radio, ShieldCheck } from "lucide-react";
import { useAnalysisStore } from "./store/useAnalysisStore";
import { Sidebar, type ViewKey } from "./components/layout/Sidebar";
import { MapView } from "./views/MapView";
import { HistoryView } from "./views/HistoryView";
import { TrendsView } from "./views/TrendsView";
import { ValidationView } from "./views/ValidationView";

const VIEW_META: Record<ViewKey, { title: string; subtitle: string }> = {
  map: {
    title: "Fire activity map",
    subtitle: "Where it burns, and how intense",
  },
  history: {
    title: "Burning history",
    subtitle: "26 years of activity at a glance",
  },
  trends: {
    title: "Trends & forecast",
    subtitle: "Seasonal shift and the next 14 days",
  },
  validation: {
    title: "Validation",
    subtitle: "Why the data is trustworthy",
  },
};

const MOBILE_NAV: Array<{ key: ViewKey; label: string; icon: typeof MapIcon }> = [
  { key: "map", label: "Map", icon: MapIcon },
  { key: "history", label: "History", icon: CalendarDays },
  { key: "trends", label: "Trends", icon: Activity },
  { key: "validation", label: "Validation", icon: ShieldCheck },
];

export default function App() {
  const [view, setView] = useState<ViewKey>("map");
  const viewMode = useAnalysisStore((state) => state.viewMode);
  const setViewMode = useAnalysisStore((state) => state.setViewMode);
  const analysisData = useAnalysisStore((state) => state.analysisData);
  const loading = useAnalysisStore((state) => state.loading);
  const executeAnalysis = useAnalysisStore((state) => state.executeAnalysis);

  const bootstrapped = useRef(false);
  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    if (!analysisData) void executeAnalysis();
  }, [analysisData, executeAnalysis]);

  const isRaw = viewMode === "RAW";
  const meta = VIEW_META[view];

  return (
    <div className="flex h-screen overflow-hidden bg-base text-ink">
      <Sidebar active={view} onChange={setView} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-center gap-3 border-b border-line bg-surface/40 px-4 py-3 md:px-6">
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold tracking-tight text-ink">
              {meta.title}
            </h1>
            <p className="truncate text-[11px] text-dim">{meta.subtitle}</p>
          </div>

          {/* RAW vs HARMONIZED regime switch */}
          <div className="ml-auto flex rounded-xl border border-line bg-base/60 p-1">
            <button
              type="button"
              onClick={() => setViewMode("RAW")}
              aria-pressed={isRaw}
              className={`flex flex-col rounded-lg px-3 py-1.5 text-left transition-colors duration-200 ${
                isRaw
                  ? "bg-danger/15 ring-1 ring-danger/40"
                  : "hover:bg-white/[0.03]"
              }`}
            >
              <span
                className={`text-xs font-semibold ${isRaw ? "text-danger" : "text-dim"}`}
              >
                Raw pixel counts
              </span>
              <span className="text-[10px] text-dim">2012 artifact</span>
            </button>
            <button
              type="button"
              onClick={() => setViewMode("HARMONIZED")}
              aria-pressed={!isRaw}
              className={`flex flex-col rounded-lg px-3 py-1.5 text-left transition-colors duration-200 ${
                !isRaw
                  ? "bg-ember/15 ring-1 ring-ember/40"
                  : "hover:bg-white/[0.03]"
              }`}
            >
              <span
                className={`text-xs font-semibold ${!isRaw ? "text-ember" : "text-dim"}`}
              >
                Harmonized energy
              </span>
              <span className="text-[10px] text-dim">Comparable series</span>
            </button>
          </div>

          {/* Live status */}
          <div className="flex items-center gap-2 rounded-xl border border-line bg-base/60 px-3 py-1.5">
            <Gauge
              className={`h-3.5 w-3.5 ${
                loading ? "animate-pulse text-heat" : "text-success"
              }`}
            />
            <span className="font-tabular text-[11px] text-dim">
              {loading
                ? "computing…"
                : analysisData?.execution_time_ms !== undefined
                  ? `${analysisData.execution_time_ms.toFixed(1)} ms`
                  : "—"}
            </span>
            <span className="h-3 w-px bg-line" />
            <span className="flex items-center gap-1 font-tabular text-[11px] text-dim">
              <Radio className="h-3 w-3 text-info" />
              {analysisData?.total_h3_cells ?? 0} cells
            </span>
          </div>
        </header>

        {/* Compact navigation for small screens */}
        <nav
          aria-label="Primary"
          className="flex gap-1 overflow-x-auto border-b border-line bg-base/40 px-3 py-2 md:hidden"
        >
          {MOBILE_NAV.map((item) => {
            const Icon = item.icon;
            const active = item.key === view;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => setView(item.key)}
                aria-current={active ? "page" : undefined}
                className={`flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                  active
                    ? "bg-white/[0.07] text-ink"
                    : "text-dim hover:text-ink"
                }`}
              >
                <Icon className={`h-3.5 w-3.5 ${active ? "text-ember" : ""}`} />
                {item.label}
              </button>
            );
          })}
        </nav>

        <main className="relative min-h-0 flex-1">
          {view === "map" && <MapView />}
          {view === "history" && <HistoryView />}
          {view === "trends" && <TrendsView />}
          {view === "validation" && <ValidationView />}
        </main>
      </div>
    </div>
  );
}
