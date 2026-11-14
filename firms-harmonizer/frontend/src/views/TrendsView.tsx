import { Activity, Sparkles } from "lucide-react";
import { PolarVonMisesClock } from "../components/Charts/PolarVonMisesClock";
import { KalmanUncertaintyBandChart } from "../components/Charts/KalmanUncertaintyBandChart";
import { ChaosMonkeyButton } from "../components/Audit/ChaosMonkeyButton";
import { InsightCard, MiniStat } from "./common";
import { useAnalysisStore } from "../store/useAnalysisStore";
import { fmt } from "../lib/format";

export function TrendsView() {
  const audit = useAnalysisStore(
    (state) => state.analysisData?.audit_metrics,
  );
  const selectedYear = useAnalysisStore((state) => state.selectedYear);
  const chaosData = useAnalysisStore((state) => state.chaosData);

  const shift = audit?.phenology_shift_days_per_decade ?? 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1320px] space-y-5 px-6 py-7">
        <div className="flex flex-wrap items-start justify-between gap-6">
          <p className="max-w-xl text-sm leading-relaxed text-dim">
            When does the fire season peak, and is it moving? The wheel shows the
            annual peak direction; the chart below shows the selected year with a
            14-day probabilistic forecast.
          </p>
          <div className="flex flex-wrap gap-7">
            <MiniStat
              label="Decadal drift"
              value={`${shift >= 0 ? "+" : ""}${fmt(shift)} d`}
              tone="text-ember"
            />
            <MiniStat label="Selected year" value={String(selectedYear)} />
            <MiniStat
              label="Forecast horizon"
              value="14 days"
              tone="text-info"
            />
            <MiniStat
              label="Recovery"
              value={chaosData ? `${fmt(chaosData.seasonal_energy_recovered_pct)}%` : "—"}
              tone="text-success"
            />
          </div>
        </div>

        <div className="grid items-start gap-5 xl:grid-cols-2">
          <PolarVonMisesClock />
          <ChaosMonkeyButton />
        </div>

        <KalmanUncertaintyBandChart />

        <div className="grid gap-4 md:grid-cols-2">
          <InsightCard
            title="A rotating fire season"
            icon={<Activity className="h-4 w-4 text-ember" />}
          >
            Each coloured spoke is one year's average burning direction. A drift
            toward later months means the fire season is shifting — the
            Theil–Sen estimate quantifies how many days per decade.
          </InsightCard>
          <InsightCard
            title="Built to survive blackouts"
            icon={<Sparkles className="h-4 w-4 text-success" />}
          >
            Run the stress test to drop 25% of VIIRS and force a 10-day blackout.
            The naive series collapses to zero; the cross-sensor guarded smoother
            reconstructs the missing energy.
          </InsightCard>
        </div>
      </div>
    </div>
  );
}
