import { ShieldCheck, GitCompare, Layers, Wind } from "lucide-react";
import { AuditMetricsPanel } from "../components/Audit/AuditMetricsPanel";
import { InsightCard } from "./common";

export function ValidationView() {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1320px] space-y-5 px-6 py-7">
        <p className="max-w-2xl text-sm leading-relaxed text-dim">
          The platform does not ask you to trust it blindly. These live checks
          compare the raw and harmonized records so you can see, statistically,
          that the sensor of origin no longer changes the story.
        </p>

        <AuditMetricsPanel />

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <InsightCard
            title="One consistent scale"
            icon={<GitCompare className="h-4 w-4 text-ember" />}
          >
            MODIS (1 km) and VIIRS (375 m) are harmonized into the same physical
            fire-energy scale, so 2012 no longer looks like a climate shock.
          </InsightCard>
          <InsightCard
            title="Gaps are reconstructed"
            icon={<Layers className="h-4 w-4 text-info" />}
          >
            Missing satellite days are filled with a guarded Kalman smoother that
            preserves seasonal energy instead of decaying to zero.
          </InsightCard>
          <InsightCard
            title="Checked against NASA"
            icon={<ShieldCheck className="h-4 w-4 text-success" />}
          >
            The harmonized record is cross-validated against independent burned
            area (MCD64A1) to confirm it tracks real fire scars.
          </InsightCard>
          <InsightCard
            title="Smoke and carbon"
            icon={<Wind className="h-4 w-4 text-heat" />}
          >
            Fire energy is converted to dry biomass burned and PM2.5 emissions
            using the Wooster conversion, ready for an IPCC-style export.
          </InsightCard>
        </div>
      </div>
    </div>
  );
}
