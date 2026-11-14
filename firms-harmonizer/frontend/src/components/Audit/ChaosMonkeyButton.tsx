import { Loader2, Play, RotateCcw, Skull, Zap } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";

/**
 * Interactive Chaos Monkey stress-test control.
 *
 * Drops 25% of VIIRS observations for the selected year and forces a 10-day
 * dual-sensor blackout, then reports how the naive series collapses while the
 * RTS Kalman + Cross-Sensor Historical Guard reconstructs the seasonal energy.
 */

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "bad";
}) {
  return (
    <div className="rounded-lg border border-line bg-base/50 px-2 py-1.5">
      <p className="font-mono text-[8px] uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p
        className={`font-mono text-sm font-bold tabular-nums ${
          tone === "ok" ? "text-emerald-400" : "text-red-400"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

export function ChaosMonkeyButton() {
  const chaosData = useAnalysisStore((state) => state.chaosData);
  const chaosLoading = useAnalysisStore((state) => state.chaosLoading);
  const triggerChaosMonkey = useAnalysisStore((state) => state.triggerChaosMonkey);
  const resetChaosMonkey = useAnalysisStore((state) => state.resetChaosMonkey);

  const recovered = chaosData?.seasonal_energy_recovered_pct ?? 0;

  return (
    <section className="flex flex-col rounded-2xl border border-line bg-surface p-4 shadow-panel">
      <header className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-100">
          <Skull className="h-4 w-4 text-red-400" />
          Chaos Monkey Resilience
        </h2>
        {chaosData && (
          <span className="rounded border border-red-700/60 bg-red-500/10 px-2 py-0.5 font-mono text-[9px] uppercase tracking-wider text-red-300">
            Sabotage active
          </span>
        )}
      </header>

      <button
        type="button"
        onClick={() => void triggerChaosMonkey()}
        disabled={chaosLoading}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-red-600 px-3 py-2 text-xs font-bold uppercase tracking-wide text-white shadow-lg shadow-red-900/40 transition-colors hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {chaosLoading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            Simulating sabotage…
          </>
        ) : (
          <>
            <Play className="h-4 w-4" />
            Run Chaos Monkey
          </>
        )}
      </button>
      <p className="mt-1 text-center font-mono text-[9px] leading-tight text-slate-500">
        Drop 25% VIIRS + 10-day dual-sensor blackout
      </p>

      <button
        type="button"
        onClick={resetChaosMonkey}
        disabled={!chaosData || chaosLoading}
        className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <RotateCcw className="h-3.5 w-3.5" />
        Reset
      </button>

      {chaosData ? (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Kpi
            label="Naive RMSE"
            value={chaosData.naive_rmse.toFixed(1)}
            tone="bad"
          />
          <Kpi
            label="RTS + Cross-Guard RMSE"
            value={chaosData.kalman_rmse.toFixed(1)}
            tone="ok"
          />
          <div className="col-span-2 flex items-center justify-center gap-2 rounded-lg border border-emerald-700/60 bg-emerald-500/10 px-2 py-1.5">
            <Zap className="h-3.5 w-3.5 text-emerald-400" />
            <span className="font-mono text-[11px] font-bold tracking-wide text-emerald-300">
              SEASONAL ENERGY RECOVERED: {recovered.toFixed(1)}%
            </span>
          </div>
          <p className="col-span-2 text-[10px] leading-snug text-slate-400">
            Dropped {chaosData.dropped_days_count} days ·{" "}
            {chaosData.dates.length} reconstructed points.
          </p>
        </div>
      ) : (
        <p className="mt-3 text-[10px] leading-snug text-slate-500">
          Wipe 25% of VIIRS and force a 10-day dual blackout, then compare the naive
          exponential decay against the RTS Kalman reconstruction and cross-sensor guard.
        </p>
      )}
    </section>
  );
}
