import { SettingsPanel } from "./components/SettingsPanel";
import { FireCopilotDrawer } from "./components/Audit/FireCopilotDrawer";
import { CubeSyncWidget } from "./components/Sync/CubeSyncWidget";
import { ObservationsPage } from "./views/ObservationsPage";
import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { Logo } from "./components/Logo";
import { useAnalysisStore } from "./store/useAnalysisStore";
import { HeatHistoryCard } from "./components/Map/HeatHistoryCard";
import { MapPage } from "./views/MapPage";
import { CalendarPage } from "./views/CalendarPage";
import { TrendsPage } from "./views/TrendsPage";
import { ImpactPage } from "./views/ImpactPage";
import { PageShell } from "./views/PageShell";
import { RiskPredictionPanel } from "./components/Risk/RiskPredictionPanel";

const SECTIONS = [
  { key: "map", label: "Map" },
  { key: "calendar", label: "Calendar" },
  { key: "trends", label: "Trends" },
  { key: "impact", label: "Impact" },
  { key: "risk", label: "Risk AI" },
  { key: "observations", label: "Observations" }
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

export default function App() {
  const [section, setSection] = useState<SectionKey>("map");
  const executeAnalysis = useAnalysisStore((s) => s.executeAnalysis);
  function openSection(next: SectionKey) {
    const state = useAnalysisStore.getState();
    if (next === "risk") void state.fetchRiskPredictionForAoi();
    setSection(next);
  }

  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void executeAnalysis();
  }, [executeAnalysis]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-paper text-ink">
      <header className="relative z-40 shrink-0 border-b border-rule">
        <div className="flex flex-wrap items-center gap-x-3 px-3 2xl:h-16 2xl:flex-nowrap lg:px-6">
          <div className="flex h-16 shrink-0 items-center gap-2.5">
            <Logo className="h-7 w-7 text-ink" />
            <span className="font-serif text-sm font-semibold text-ink tracking-[-0.01em] sm:text-base">FIRMS Harmonizer</span>
          </div>

          <nav aria-label="Main sections" className="order-last flex w-full items-stretch justify-between overflow-x-auto border-t border-rule 2xl:order-none 2xl:h-full 2xl:w-auto 2xl:flex-1 2xl:justify-center 2xl:border-t-0">
            {SECTIONS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => openSection(item.key)}
                aria-current={section === item.key ? "page" : undefined}
                className={`flex-1 border-b-2 px-3 py-3 text-sm font-medium transition-colors 2xl:flex-none 2xl:px-4 ${
                  section === item.key ? "border-reference text-reference" : "border-transparent text-muted hover:bg-panel hover:text-ink"
                }`}
              >
                {item.label}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex max-w-full flex-wrap items-center gap-2 pb-2 2xl:pb-0">
            <CubeSyncWidget />
            <button type="button" onClick={() => useAnalysisStore.getState().toggleCopilot()} className="flex items-center gap-1 border border-rule px-2 py-1.5 text-xs"><Sparkles className="h-4 w-4" />Fire Copilot</button>
            <SettingsPanel />

          </div>
        </div>
      </header>

      <div className="relative flex min-h-0 flex-1 flex-col">
        <main className="relative z-0 min-h-0 flex-1" onKeyDown={(e) => {
          if (e.target instanceof HTMLElement && e.target.closest("input, select, textarea, [contenteditable=true]")) return;
          const state = useAnalysisStore.getState();
          const direction = e.key === "ArrowLeft" || e.key === "[" || e.key === "ArrowDown" ? -1 : 1;
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
          {section === "risk" && (
            <PageShell
              eyebrow="Classical AI Forecasting"
              title="Thermal risk forecast"
            >
              <RiskPredictionPanel />
            </PageShell>
          )}
          {section === "observations" && <ObservationsPage />}
          <FireCopilotDrawer />
        </main>
        <HeatHistoryCard />
      </div>
    </div>
  );
}
