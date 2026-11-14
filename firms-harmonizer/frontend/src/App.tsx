import { useEffect, useRef, useState } from "react";
import { Flame } from "lucide-react";
import { useAnalysisStore } from "./store/useAnalysisStore";
import { HeatHistoryCard } from "./components/Map/HeatHistoryCard";
import { MapPage } from "./views/MapPage";
import { CalendarPage } from "./views/CalendarPage";
import { TrendsPage } from "./views/TrendsPage";
import { ImpactPage } from "./views/ImpactPage";

const SECTIONS = [
  { key: "map", label: "Map" },
  { key: "calendar", label: "Calendar" },
  { key: "trends", label: "Trends" },
  { key: "impact", label: "Impact" }
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

export default function App() {
  const [section, setSection] = useState<SectionKey>("map");
  const viewMode = useAnalysisStore((s) => s.viewMode);
  const setViewMode = useAnalysisStore((s) => s.setViewMode);
  const executeAnalysis = useAnalysisStore((s) => s.executeAnalysis);

  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void executeAnalysis();
  }, [executeAnalysis]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-paper text-ink">
      <header className="relative z-40 shrink-0 border-b border-rule">
        <div className="flex flex-wrap items-center gap-x-3 px-3 lg:h-16 lg:flex-nowrap lg:px-6">
          <div className="flex h-16 shrink-0 items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-sm bg-ink text-paper">
              <Flame className="h-4 w-4" />
            </span>
            <span className="font-serif text-sm font-semibold text-ink sm:text-base">FIRMS Harmonizer</span>
          </div>

          <nav aria-label="Main sections" className="order-last flex w-full items-stretch justify-between border-t border-rule lg:order-none lg:h-full lg:w-auto lg:flex-1 lg:justify-center lg:border-t-0">
            {SECTIONS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setSection(item.key)}
                aria-current={section === item.key ? "page" : undefined}
                className={`flex-1 border-b-2 px-3 py-3 text-sm font-medium transition-colors lg:flex-none lg:px-7 ${
                  section === item.key ? "border-reference text-reference" : "border-transparent text-muted hover:bg-panel hover:text-ink"
                }`}
              >
                {item.label}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <div className="inline-flex border border-rule text-xs">
              <button
                type="button"
                onClick={() => setViewMode("RAW")}
                aria-pressed={viewMode === "RAW"}
                className={`px-2 py-1.5 sm:px-3 ${viewMode === "RAW" ? "bg-ink text-paper" : "text-muted hover:bg-paper"}`}
              >
                Raw
              </button>
              <button
                type="button"
                onClick={() => setViewMode("HARMONIZED")}
                aria-pressed={viewMode === "HARMONIZED"}
                className={`border-l border-rule px-2 py-1.5 sm:px-3 ${viewMode === "HARMONIZED" ? "bg-ink text-paper" : "text-muted hover:bg-paper"}`}
              >
                Harmonized
              </button>
            </div>

          </div>
        </div>
      </header>

      <main className="relative min-h-0 flex-1" onKeyDown={(e) => {
        if (e.target instanceof HTMLElement && e.target.closest("input, select, textarea, [contenteditable=true]")) return;
        const state = useAnalysisStore.getState();
        const direction = e.key === "ArrowLeft" || e.key === "[" || e.key === "ArrowUp" ? -1 : 1;
        if (["ArrowLeft", "ArrowRight", "[", "]", "ArrowUp", "ArrowDown"].includes(e.key)) {
          e.preventDefault();
          state.stepChronology(e.key === "[" || e.key === "]" ? "month" : e.key === "ArrowUp" || e.key === "ArrowDown" ? "year" : "day", direction);
        } else if (e.key === "Escape") {
          e.preventDefault(); state.setSelectedMonth(null); state.setHoveredDay(null);
        }
      }}>
        {section === "map" && <MapPage />}
        {section === "calendar" && <CalendarPage />}
        {section === "trends" && <TrendsPage />}
        {section === "impact" && <ImpactPage />}
      </main>
      <HeatHistoryCard />
    </div>
  );
}
