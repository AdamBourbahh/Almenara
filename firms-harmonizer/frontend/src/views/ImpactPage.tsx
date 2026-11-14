import { AuditMetricsPanel } from "../components/Audit/AuditMetricsPanel";
import { RiskPredictionPanel } from "../components/Risk/RiskPredictionPanel";
import { PageShell } from "./PageShell";

export function ImpactPage() {
  return (
    <PageShell
      eyebrow="Impact and evidence"
      title="What it means in biomass, smoke and statistical confidence"
      intro="First the physical impact in plain terms. Below it, the tests that show the harmonized record holds up against independent data."
    >
      <AuditMetricsPanel />
      <RiskPredictionPanel />
    </PageShell>
  );
}
