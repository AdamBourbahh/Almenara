import { useEffect, useRef, useState } from "react";
import { Flame, Sparkles } from "lucide-react";
import { PRESET_ORDER, PRESET_REGIONS, useAnalysisStore } from "./store/useAnalysisStore";
import { MapPage } from "./views/MapPage";
import { BurningCalendarCanvas } from "./components/Calendar/BurningCalendarCanvas";
import { FireCopilotDrawer } from "./components/Audit/FireCopilotDrawer";

export default function App() {
  const [section, setSection] = useState("map");
  const data = useAnalysisStore((s) => s.observationData);
  const selected = useAnalysisStore((s) => s.selectedPreset);
  const load = useAnalysisStore((s) => s.loadPresetRegion);
  const execute = useAnalysisStore((s) => s.executeAnalysis);
  const loading = useAnalysisStore((s) => s.loading);
  const error = useAnalysisStore((s) => s.error);
  const openCopilot = useAnalysisStore((s) => s.openCopilot);
  const isCopilotOpen = useAnalysisStore((s) => s.isCopilotOpen);
  const toggleCopilot = useAnalysisStore((s) => s.toggleCopilot);
  const activeSpikeDay = useAnalysisStore((s) => s.activeSpikeDay);

  const booted = useRef(false);
  useEffect(() => { if (!booted.current) { booted.current = true; void execute(); } }, [execute]);
  const exportCsv = () => {
    if (!data) return;
    const rows = ["date,detection_count,summed_instantaneous_frp_mw,sensors,data_source", ...data.daily.map((d) => `${d.date},${d.detection_count},${d.raw_frp_mw},${d.sensors.join("|")},real`)];
    const url = URL.createObjectURL(new Blob([rows.join("\r\n")], {type: "text/csv;charset=utf-8"}));
    const a = document.createElement("a"); a.href = url; a.download = `FIRMS_observations_${selected}.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
  };
  return <div className="flex h-screen flex-col overflow-hidden bg-paper text-ink">
    <header className="z-40 flex shrink-0 flex-wrap items-center gap-3 border-b border-rule bg-panel px-4 py-3">
      <Flame className="h-5 w-5" /><h1 className="font-serif font-semibold">FIRMS Observations</h1>
      <select aria-label="Study region" value={selected} onChange={(e) => void load(e.target.value)} className="min-w-0 border border-rule bg-paper px-2 py-2 text-xs">
        {selected === "CUSTOM" && <option value="CUSTOM">Custom area</option>}
        {PRESET_ORDER.map((key) => <option key={key} value={key}>{PRESET_REGIONS[key].label}</option>)}
      </select>
      <nav aria-label="Main sections" className="flex gap-1">
        {["map", "calendar"].map((key) => <button key={key} onClick={() => setSection(key)} aria-current={section === key ? "page" : undefined} className={`border border-rule px-3 py-2 text-xs ${section === key ? "bg-ink text-paper" : ""}`}>{key === "map" ? "Map" : "Daily record"}</button>)}
      </nav>
      <span className="text-xs text-muted" role="status">{loading ? "Loading real observations…" : data ? `${data.total_detections.toLocaleString("en-US")} satellite detections · real data` : "Observations unavailable"}</span>
      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          onClick={() => (toggleCopilot ? toggleCopilot() : openCopilot())}
          className={`inline-flex items-center gap-1.5 border border-rule px-2.5 py-2 text-xs font-medium transition-colors ${
            isCopilotOpen ? "bg-ink text-paper" : "hover:bg-paper"
          }`}
          title="Toggle Fire Copilot AI Inspector"
        >
          <Sparkles className="h-3.5 w-3.5 text-terracotta" />
          <span>Fire Copilot</span>
          {activeSpikeDay && (
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" title="Active spike context" />
          )}
        </button>
        <button onClick={exportCsv} disabled={!data?.daily.length || loading} className="border border-rule px-3 py-2 text-xs disabled:opacity-40">Export observations CSV</button>
      </div>
    </header>
    {error && <div role="alert" className="flex items-center gap-3 border-b border-rule bg-panel px-4 py-3 text-sm text-bias"><span>Could not load real observations: {error}</span><button className="underline" onClick={() => void execute()}>Retry</button></div>}
    {!loading && data && !data.daily.length && <p role="status" className="border-b border-rule px-4 py-3 text-sm">No reported detections inside this area. This does not establish zero fire activity.</p>}
    <main className="relative min-h-0 flex-1">
      <div className={section === "map" ? "h-full" : "invisible absolute inset-0 pointer-events-none"}><MapPage /></div>
      {section === "calendar" && <div className="h-full overflow-y-auto px-4 py-6"><div className="mx-auto max-w-[1400px]"><h2 className="font-serif text-2xl">Daily satellite detections</h2><p className="my-3 text-sm text-muted">{data?.first_observed_date ?? "—"} to {data?.last_observed_date ?? "—"}. Counts are satellite detections, not individual fires. Blank days have no reported detections; observation coverage is unknown.</p><BurningCalendarCanvas /></div></div>}
    </main>
    <FireCopilotDrawer />
  </div>;
}
