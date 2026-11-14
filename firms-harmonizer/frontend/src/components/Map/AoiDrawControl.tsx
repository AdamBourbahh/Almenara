import { useState } from "react";
import {
  ChevronDown,
  Crosshair,
  Layers,
  RefreshCw,
  SlidersHorizontal,
} from "lucide-react";
import { useAnalysisStore, PRESET_REGIONS } from "../../store/useAnalysisStore";

function Field({
  label,
  value,
  onChange,
  step,
  min,
  max,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  step?: string;
  min?: string;
  max?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-medium text-dim">{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        max={max}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 rounded-lg border border-line bg-base/70 px-2 font-mono text-xs text-ink outline-none focus:border-ember/50"
      />
    </label>
  );
}

export function AoiDrawControl() {
  const selectedPreset = useAnalysisStore((state) => state.selectedPreset);
  const loadPresetRegion = useAnalysisStore((state) => state.loadPresetRegion);
  const setCustomAoi = useAnalysisStore((state) => state.setCustomAoi);
  const excludeIndustrial = useAnalysisStore((state) => state.excludeIndustrial);
  const setExcludeIndustrial = useAnalysisStore(
    (state) => state.setExcludeIndustrial,
  );
  const highlightIndustrialOnMap = useAnalysisStore(
    (state) => state.highlightIndustrialOnMap,
  );
  const setHighlightIndustrialOnMap = useAnalysisStore(
    (state) => state.setHighlightIndustrialOnMap,
  );
  const analysisData = useAnalysisStore((state) => state.analysisData);
  const loading = useAnalysisStore((state) => state.loading);
  const executeAnalysis = useAnalysisStore((state) => state.executeAnalysis);

  const [showCustom, setShowCustom] = useState(false);
  const [lat, setLat] = useState("-29.5");
  const [lon, setLon] = useState("-67.4");
  const [radius, setRadius] = useState("0.3");

  const applyCustom = () => {
    const latitude = Number(lat);
    const longitude = Number(lon);
    const half = Math.min(Math.abs(Number(radius)) || 0.3, 5);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
    void setCustomAoi([
      [
        [longitude - half, latitude - half],
        [longitude + half, latitude - half],
        [longitude + half, latitude + half],
        [longitude - half, latitude + half],
        [longitude - half, latitude - half],
      ],
    ]);
  };

  const keys = Object.keys(PRESET_REGIONS) as Array<keyof typeof PRESET_REGIONS>;

  return (
    <div className="glass absolute left-4 top-4 z-20 w-[300px] rounded-2xl p-3 shadow-float">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-dim">
          <Crosshair className="h-3 w-3 text-ember" />
          Area of interest
        </p>
        <span className="font-mono text-[10px] text-dim">
          {analysisData?.total_h3_cells ?? 0} cells
        </span>
      </div>

      <div className="relative mt-2">
        <select
          value={selectedPreset}
          onChange={(event) =>
            void loadPresetRegion(
              event.target.value as keyof typeof PRESET_REGIONS,
            )
          }
          className="h-9 w-full appearance-none rounded-lg border border-line bg-base/70 px-3 pr-8 text-xs font-medium text-ink outline-none focus:border-ember/50"
        >
          {keys.map((key) => (
            <option key={key} value={key} className="bg-surface text-ink">
              {PRESET_REGIONS[key].name}
            </option>
          ))}
          {selectedPreset === "CUSTOM" && (
            <option value="CUSTOM" className="bg-surface text-ink">
              Custom area
            </option>
          )}
        </select>
        <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-dim" />
      </div>

      <button
        type="button"
        onClick={() => setShowCustom((value) => !value)}
        className="mt-2 flex items-center gap-1.5 text-[11px] font-medium text-dim transition-colors hover:text-ink"
      >
        <SlidersHorizontal className="h-3 w-3" />
        {showCustom ? "Hide coordinates" : "Enter coordinates"}
      </button>

      {showCustom && (
        <div className="mt-2 rounded-xl border border-line bg-base/40 p-2">
          <div className="grid grid-cols-3 gap-2">
            <Field label="Latitude" value={lat} onChange={setLat} step="0.1" />
            <Field label="Longitude" value={lon} onChange={setLon} step="0.1" />
            <Field
              label="± degrees"
              value={radius}
              onChange={setRadius}
              step="0.1"
              min="0.1"
              max="5"
            />
          </div>
          <button
            type="button"
            onClick={applyCustom}
            className="mt-2 h-8 w-full rounded-lg bg-ember/15 text-[11px] font-semibold text-ember transition-colors hover:bg-ember/25"
          >
            Analyze this area
          </button>
        </div>
      )}

      <div className="mt-3 space-y-1.5 border-t border-line pt-3">
        <label className="flex cursor-pointer items-center justify-between gap-2 text-[11px] text-dim">
          <span className="flex items-center gap-1.5">
            <Layers className="h-3 w-3" />
            Highlight gas flaring
          </span>
          <input
            type="checkbox"
            checked={highlightIndustrialOnMap}
            onChange={(event) =>
              setHighlightIndustrialOnMap(event.target.checked)
            }
            className="h-3.5 w-3.5 accent-ember"
          />
        </label>
        <label className="flex cursor-pointer items-center justify-between gap-2 text-[11px] text-dim">
          <span className="flex items-center gap-1.5">
            <Layers className="h-3 w-3" />
            Exclude industrial flares
          </span>
          <input
            type="checkbox"
            checked={excludeIndustrial}
            onChange={(event) => setExcludeIndustrial(event.target.checked)}
            className="h-3.5 w-3.5 accent-ember"
          />
        </label>
      </div>

      <div className="mt-3 flex items-center justify-between border-t border-line pt-2">
        <span className="font-mono text-[10px] text-dim">
          {loading
            ? "computing…"
            : `${analysisData?.execution_time_ms?.toFixed(1) ?? "—"} ms`}
        </span>
        <button
          type="button"
          onClick={() => void executeAnalysis()}
          title="Refresh analysis"
          aria-label="Refresh analysis"
          className="flex h-7 w-7 items-center justify-center rounded-lg text-dim transition-colors hover:bg-white/5 hover:text-ink"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>
    </div>
  );
}
