import { useEffect, useRef, useState } from "react";
import { Moon, Settings, Sun, X } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { useAnalysisStore } from "../store/useAnalysisStore";
import { useTheme } from "../lib/theme";

export function SettingsPanel() {
  const [open,setOpen]=useState(false);
  const container=useRef<HTMLDivElement>(null);
  const theme=useTheme(s=>s.theme);
  const toggleTheme=useTheme(s=>s.toggle);
  const state=useAnalysisStore(useShallow(s=>({viewMode:s.viewMode,setViewMode:s.setViewMode,
    analysisData:s.analysisData,loading:s.loading,excludeIndustrial:s.excludeIndustrial,
    setExcludeIndustrial:s.setExcludeIndustrial,highlightIndustrialOnMap:s.highlightIndustrialOnMap,
    setHighlightIndustrialOnMap:s.setHighlightIndustrialOnMap})));
  const candidates=(state.analysisData?.map_hexagons ?? []).filter(c=>c.is_industrial_site).length;
  useEffect(()=>{
    const outside=(e:PointerEvent)=>{if(e.target instanceof Node && !container.current?.contains(e.target))setOpen(false);};
    const escape=(e:KeyboardEvent)=>{if(e.key==='Escape' && open){e.stopPropagation();setOpen(false);}};
    document.addEventListener('pointerdown',outside);
    document.addEventListener('keydown',escape,true);
    return ()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape,true);};
  },[open]);
  return <div ref={container} className="relative flex items-center gap-2">
    <button type="button" onClick={toggleTheme} aria-label={theme==='dark'?'Switch to light mode':'Switch to dark mode'} title="Appearance" className="border border-rule p-1.5 text-muted hover:bg-paper">{theme==='dark'?<Sun className="h-4 w-4"/>:<Moon className="h-4 w-4"/>}</button>
    <button type="button" aria-label="Settings" aria-expanded={open} onClick={()=>setOpen(!open)} className="flex items-center gap-1 border border-rule px-2 py-1.5 text-xs"><Settings className="h-4 w-4"/>Settings</button>
    {open && <section aria-label="Settings panel" className="absolute right-0 top-full z-50 mt-2 max-h-[70vh] w-[min(360px,90vw)] space-y-4 overflow-y-auto rounded-lg border border-rule bg-panel p-4 text-xs text-ink shadow-xl">
      <div className="flex items-center justify-between"><h2 className="font-serif text-base">Settings</h2><button type="button" aria-label="Close settings" onClick={()=>setOpen(false)}><X className="h-4 w-4"/></button></div>
      <label className="block space-y-1"><span className="font-medium">Map and calendar display</span><select aria-label="Data display" value={state.viewMode} onChange={e=>state.setViewMode(e.target.value as 'RAW'|'HARMONIZED')} className="w-full border border-rule bg-paper p-2"><option value="HARMONIZED">Calibrated energy</option><option value="RAW">Detection count</option></select></label>
      <p className="text-faint">Detection count shows satellite observations. Calibrated energy accounts for sensor differences. Changing the display does not change the reported energy totals.</p>
      <fieldset className="space-y-2 border-t border-rule pt-3"><legend className="font-medium">Industrial heat screening</legend>
        <label className="flex items-start gap-2"><input type="checkbox" checked={state.excludeIndustrial} onChange={e=>void state.setExcludeIndustrial(e.target.checked)}/><span>Exclude industrial heat candidates from analysis</span></label>
        <label className="flex items-start gap-2"><input type="checkbox" checked={state.highlightIndustrialOnMap} onChange={e=>state.setHighlightIndustrialOnMap(e.target.checked)}/><span>Highlight industrial heat candidates in purple</span></label>
        <p role="status" className="text-faint">{state.loading?'Checking selected area…':`${candidates} candidate cells in this area's full record.`} {candidates===0 && !state.loading?'With no flagged cells, these controls have no visible effect.':''}</p>
        <p className="text-faint">Persistent heat can come from refineries or flares. A screening flag is not confirmation of a facility.</p>
      </fieldset>
      <details className="border-t border-rule pt-3"><summary className="cursor-pointer font-medium">Keyboard shortcuts</summary><dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-muted">
        <dt><kbd>H</kbd></dt><dd>Show or hide heat on the map</dd>
        <dt><kbd>← / →</kbd></dt><dd>Previous / next day (main workspace)</dd>
        <dt><kbd>[ / ]</kbd></dt><dd>Previous / next month</dd>
        <dt><kbd>↑ / ↓</kbd></dt><dd>Previous / next year (main workspace)</dd>
        <dt><kbd>Ctrl / ⌘ + + / −</kbd></dt><dd>Zoom while the pointer is over the map</dd>
        <dt><kbd>Ctrl / ⌘ + 0</kbd></dt><dd>Fit the selected area to the map</dd>
        <dt><kbd>Ctrl + wheel</kbd></dt><dd>Zoom the map</dd>
        <dt><kbd>Esc</kbd></dt><dd>Close settings or cancel area drawing; otherwise clear month selection</dd>
      </dl><p className="mt-2 text-faint">The focused timeline uses its own arrow keys. Shortcuts do not run while typing in a field.</p></details>
    </section>}
  </div>;
}
