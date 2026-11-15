import { PolarVonMisesClock } from "../components/Charts/PolarVonMisesClock";
import { KalmanUncertaintyBandChart } from "../components/Charts/KalmanUncertaintyBandChart";
import { PageShell } from "./PageShell";

export function TrendsPage() {
  return (
    <PageShell
      eyebrow="Season and gaps"
      title="When the fire season peaks, and what happens when a satellite drops out"
      intro="The clock shows where each year's burning is concentrated. The chart on the right reconstructs repaired days from the cross-sensor prior and neighbouring observations when a measurement is missing."
    >
      <div className="grid items-start gap-6 lg:grid-cols-5">
        <div className="lg:col-span-2"><PolarVonMisesClock /></div>
        <div className="lg:col-span-3"><KalmanUncertaintyBandChart /></div>
      </div>
    </PageShell>
  );
}
