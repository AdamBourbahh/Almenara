import { useEffect, useRef, useState } from "react";
import { ChevronDown, Flame, Moon, Sun } from "lucide-react";
import { useAnalysisStore } from "./store/useAnalysisStore";
import { useTheme } from "./lib/theme";
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
  const [menuOpen, setMenuOpen] = useState(false);
  const viewMode = useAnalysisStore((s) => s.viewMode);
  const setViewMode = useAnalysisStore((s) => s.setViewMode);
  const executeAnalysis = useAnalysisStore((s) => s.executeAnalysis);
  const analysisData = useAnalysisStore((s) => s.analysisData);
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggle);

  const booted = useRef(false);
  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    void executeAnalysis();
  }, [executeAnalysis]);

  const current = SECTIONS.find((s) => s.key === section) ?? SECTIONS[0];

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-paper text-ink">
      <header className="relative z-40 shrink-0 border-b border-rule">
        <div className="flex h-14 items-center gap-3 px-4 md:px-6">
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-sm bg-ink text-paper">
              <Flame className="h-4 w-4" />
            </span>
            <span className="font-serif text-base font-semibold text-ink">FIRMS Harmonizer</span>
          </div>

          <div className="relative">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
              className="flex items-center gap-1.5 border border-rule px-3 py-1.5 text-xs font-medium text-ink hover:bg-paper"
            >
              {current.label}
              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${menuOpen ? "rotate-180" : ""}`} />
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} aria-hidden="true" />
                <div role="menu" className="absolute left-0 top-full z-50 mt-1 w-44 border border-rule bg-panel py-1">
                  {SECTIONS.map((s) => (
                    <button
                      key={s.key}
                      role="menuitem"
                      type="button"
                      onClick={() => {
                        setSection(s.key);
                        setMenuOpen(false);
                      }}
                      className={`flex w-full items-center px-3 py-2 text-left text-xs ${
                        s.key === section ? "bg-paper font-medium text-ink" : "text-muted hover:bg-paper hover:text-ink"
                      }`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          <div className="ml-auto flex items-center gap-2">
            <div className="inline-flex border border-rule text-xs">
              <button
                type="button"
                onClick={() => setViewMode("RAW")}
                aria-pressed={viewMode === "RAW"}
                className={`px-3 py-1.5 ${viewMode === "RAW" ? "bg-ink text-paper" : "text-muted hover:bg-paper"}`}
              >
                Raw
              </button>
              <button
                type="button"
                onClick={() => setViewMode("HARMONIZED")}
                aria-pressed={viewMode === "HARMONIZED"}
                className={`border-l border-rule px-3 py-1.5 ${viewMode === "HARMONIZED" ? "bg-ink text-paper" : "text-muted hover:bg-paper"}`}
              >
                Harmonized
              </button>
            </div>

            <button
              type="button"
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
              className="border border-rule p-1.5 text-muted hover:bg-paper hover:text-ink"
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>

            <span className="hidden items-center gap-1 font-mono text-[10px] text-faint md:inline-flex tnum">
              {analysisData?.execution_time_ms !== undefined ? `${analysisData.execution_time_ms.toFixed(0)} ms` : "—"}
            </span>
          </div>
        </div>
      </header>

      <main className="relative min-h-0 flex-1">
        {section === "map" && <MapPage />}
        {section === "calendar" && <CalendarPage />}
        {section === "trends" && <TrendsPage />}
        {section === "impact" && <ImpactPage />}
      </main>
    </div>
  );
}
