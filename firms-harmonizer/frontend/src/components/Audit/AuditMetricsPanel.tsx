import { Download } from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import { exportToIpccCsv } from "../../api/client";

function fmt(value: number | null | undefined, digits = 1): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function fmtP(p: number): string {
  if (!Number.isFinite(p)) return "—";
  if (p <= 0) return "< 1e-300";
  if (p < 1e-4) return p.toExponential(1);
  return p.toFixed(3);
}

function Cell({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="px-4 py-3">
      <p className="text-[11px] text-faint">{label}</p>
      <p className="mt-0.5 font-serif text-xl text-ink tnum">
        {value}
        {unit && <span className="ml-1 font-sans text-xs font-normal text-faint">{unit}</span>}
      </p>
    </div>
  );
}

function Verdict({ ok }: { ok: boolean }) {
  return ok ? (
    <span className="font-medium text-validated">[VALIDATED]</span>
  ) : (
    <span className="font-medium text-bias">[BIAS DETECTED]</span>
  );
}

export function AuditMetricsPanel() {
  const analysisData = useAnalysisStore((s) => s.analysisData);
  const audit = analysisData?.audit_metrics;

  if (!analysisData || !audit) {
    return (
      <section className="border border-rule bg-panel p-6">
        <h3 className="font-serif text-xl text-ink">Environmental impact and scientific audit</h3>
        <p className="mt-2 text-sm text-muted">Run an analysis to see the impact and the validation checks.</p>
      </section>
    );
  }

  const biomass = audit.total_biomass_burned_kt ?? 0;
  const pm25 = audit.total_pm25_emitted_tonnes ?? 0;
  const area = analysisData.aoi_area_km2;
  const w1Reduction =
    audit.wasserstein_w1_raw > 0 ? (1 - audit.wasserstein_w1_harm / audit.wasserstein_w1_raw) * 100 : 0;
  const chowPass = audit.chow_test_p_val_harm > 0.1;
  const r2Pass = (audit.burned_area_r2_harm ?? 0) >= 0.7;

  const verdict =
    `The harmonized series smooths the artificial 2012 jump (the Chow test ${chowPass ? "passes" : "does not pass"}) ` +
    `and cuts the gap between sensors by ${w1Reduction.toFixed(0)}%. Correlation with real burned area rises ` +
    `from R² ${fmt(audit.burned_area_r2_raw, 2)} to ${fmt(audit.burned_area_r2_harm, 2)}.`;

  return (
    <section className="border border-rule bg-panel p-6">
      <header className="mb-1">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">Impact and validation</p>
        <h3 className="mt-1 font-serif text-xl text-ink">Environmental impact and scientific audit</h3>
      </header>
      <p className="mb-5 max-w-2xl text-sm leading-relaxed text-muted">
        First the physical impact in plain terms. Below it, the checks that show the harmonization is
        real and not just a coat of paint.
      </p>

      <div className="border border-rule">
        <div className="grid grid-cols-1 divide-y divide-rule sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <Cell label="Dry biomass burned" value={fmt(biomass)} unit="kt" />
          <Cell label="PM2.5 smoke emissions" value={fmt(pm25)} unit="t" />
          <Cell label="Area analysed" value={fmt(area, 0)} unit="km²" />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-rule p-4">
          <p className="max-w-2xl text-sm leading-relaxed text-muted">{verdict}</p>
          <button
            type="button"
            onClick={() => exportToIpccCsv(analysisData)}
            className="flex shrink-0 items-center gap-2 border border-ink/20 px-3 py-2 text-xs font-medium text-ink hover:bg-paper"
          >
            <Download className="h-3.5 w-3.5" />
            Download harmonized series (IPCC-ready CSV)
          </button>
        </div>
      </div>

      <h4 className="mb-2 mt-7 text-xs font-medium uppercase tracking-[0.12em] text-faint">
        Statistical validation (researchers)
      </h4>
      <div className="overflow-x-auto border border-rule">
        <table className="w-full min-w-[640px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-rule bg-paper text-left text-faint">
              <th className="px-3 py-2 font-medium">Test</th>
              <th className="px-3 py-2 text-right font-medium">Raw data</th>
              <th className="px-3 py-2 text-right font-medium">Harmonized series</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            <tr>
              <td className="px-3 py-2 text-ink">Chow structural break (Jan 2012)</td>
              <td className="px-3 py-2 text-right text-muted tnum">
                F {fmt(audit.chow_test_f_stat_raw, 2)} · p {fmtP(audit.chow_test_p_val_raw)}
              </td>
              <td className="px-3 py-2 text-right text-muted tnum">
                F {fmt(audit.chow_test_f_stat_harm, 2)} · p {fmtP(audit.chow_test_p_val_harm)}
              </td>
              <td className="px-3 py-2">
                <Verdict ok={chowPass} />
              </td>
            </tr>
            <tr>
              <td className="px-3 py-2 text-ink">Wasserstein distance (W1)</td>
              <td className="px-3 py-2 text-right text-muted tnum">{fmt(audit.wasserstein_w1_raw, 3)}</td>
              <td className="px-3 py-2 text-right text-muted tnum">{fmt(audit.wasserstein_w1_harm, 3)}</td>
              <td className="px-3 py-2">
                <Verdict ok={w1Reduction >= 50} />
              </td>
            </tr>
            <tr>
              <td className="px-3 py-2 text-ink">R² vs burned area (MCD64A1)</td>
              <td className="px-3 py-2 text-right text-muted tnum">{fmt(audit.burned_area_r2_raw, 3)}</td>
              <td className="px-3 py-2 text-right text-muted tnum">{fmt(audit.burned_area_r2_harm, 3)}</td>
              <td className="px-3 py-2">
                <Verdict ok={r2Pass} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-faint">
        Temporal entropy filter: {audit.industrial_false_positives_removed.toLocaleString("en-US")} industrial
        sources discarded (H &gt; 0.75). Peak drift: {fmt(audit.phenology_shift_days_per_decade)} days per
        decade; Mann–Kendall p = {fmtP(audit.mann_kendall_p_value)}.
      </p>
    </section>
  );
}
