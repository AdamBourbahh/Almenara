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

type CheckState = "pass" | "fail" | "descriptive" | "na";

const STATUS_STYLE: Record<CheckState, { label: string; className: string }> = {
  pass: { label: "Pass", className: "border-validated/30 bg-validated/10 text-validated" },
  fail: { label: "Not met", className: "border-bias/30 bg-bias/10 text-bias" },
  descriptive: { label: "Descriptive", className: "border-rule-strong bg-paper text-muted" },
  na: { label: "Not available", className: "border-rule bg-paper text-faint" }
};

function Status({ state }: { state: CheckState }) {
  const { label, className } = STATUS_STYLE[state];
  return <span className={`inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>{label}</span>;
}

/** Split the server verdict into sentences without breaking decimals such as "p=0.0335". */
function sentences(text: string): string[] {
  return text.split(/(?<=[.!?])\s+(?=[A-Z])/).map((part) => part.trim()).filter(Boolean);
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
  const pm25 = audit.total_pm25_emitted_tonnes;
  const area = analysisData.aoi_area_km2;
  const w1Reduction =
    audit.wasserstein_w1_raw > 0 ? (1 - audit.wasserstein_w1_harm / audit.wasserstein_w1_raw) * 100 : 0;
  const chowPass = audit.chow_test_p_val_harm > 0.1;
  const w1Pass = audit.wasserstein_w1_raw > 0 && w1Reduction > 88;
  const r2Available = audit.burned_area_r2_harm != null;
  const verdict = sentences(`${audit.executive_verdict_en ?? ""} ${analysisData.coverage_note ?? ""}`);
  const headline = verdict.slice(0, 2);
  const notes = verdict.slice(2);

  return (
    <section className="border border-rule bg-panel p-6">
      <header className="mb-1">
        <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">Impact and validation</p>
        <h3 className="mt-1 font-serif text-xl text-ink">Environmental impact and scientific audit</h3>
      </header>
      <p className="mb-5 max-w-2xl text-sm leading-relaxed text-muted">
        Totals cover the whole record for the selected area.
      </p>

      <div className="border border-rule">
        <div className="grid grid-cols-1 divide-y divide-rule sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <Cell label="Dry biomass estimate" value={fmt(biomass)} unit="kt" />
          <Cell
            label="PM2.5 smoke emissions"
            value={pm25 == null ? "Not computed" : fmt(pm25)}
            unit={pm25 == null ? undefined : "t"}
          />
          <Cell label="Polygon area" value={fmt(area, 0)} unit="km²" />
        </div>
        <div className="flex flex-wrap items-start justify-between gap-4 border-t border-rule p-4">
          <div className="min-w-0 max-w-2xl flex-1 text-sm leading-relaxed text-muted">
            <ul className="space-y-1.5">
              {headline.map((line) => <li key={line} className="text-ink">{line}</li>)}
            </ul>
            {notes.length > 0 && (
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer font-medium text-reference">Method notes ({notes.length})</summary>
                <ul className="mt-2 list-disc space-y-1 pl-4">
                  {notes.map((line) => <li key={line}>{line}</li>)}
                </ul>
              </details>
            )}
          </div>
          <button
            type="button"
            onClick={() => exportToIpccCsv(analysisData)}
            className="flex shrink-0 items-center gap-2 border border-ink/20 px-3 py-2 text-xs font-medium text-ink hover:bg-paper"
          >
            <Download className="h-3.5 w-3.5" />
            Download energy estimates (research CSV)
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
              <th className="px-3 py-2 font-medium">Test and what it shows</th>
              <th className="px-3 py-2 text-right font-medium">Raw data</th>
              <th className="px-3 py-2 text-right font-medium">Harmonized series</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            <tr>
              <td className="px-3 py-2 text-ink">
                Chow structural break (Jan 2012)
                <span className="block text-[11px] text-faint">
                  {chowPass ? "No break at 2012 after harmonization: the series is continuous." : "A break at 2012 remains after harmonization (gate: p > 0.10)."}
                </span>
              </td>
              <td className="px-3 py-2 text-right text-muted tnum">
                F {fmt(audit.chow_test_f_stat_raw, 2)} · p {fmtP(audit.chow_test_p_val_raw)}
              </td>
              <td className="px-3 py-2 text-right text-muted tnum">
                F {fmt(audit.chow_test_f_stat_harm, 2)} · p {fmtP(audit.chow_test_p_val_harm)}
              </td>
              <td className="px-3 py-2">
                <Status state={chowPass ? "pass" : "fail"} />
              </td>
            </tr>
            <tr>
              <td className="px-3 py-2 text-ink">
                Wasserstein distance (W1)
                <span className="block text-[11px] text-faint">
                  How different the pre- and post-2012 distributions are. Target: at least 88% less.
                </span>
              </td>
              <td className="px-3 py-2 text-right text-muted tnum">{fmt(audit.wasserstein_w1_raw, 3)}</td>
              <td className="px-3 py-2 text-right text-muted tnum">
                {fmt(audit.wasserstein_w1_harm, 3)} · {w1Reduction.toFixed(1)}% reduction
              </td>
              <td className="px-3 py-2">
                <Status state={w1Pass ? "pass" : "fail"} />
              </td>
            </tr>
            <tr>
              <td className="px-3 py-2 text-ink">
                R² vs burned area (MCD64A1)
                <span className="block text-[11px] text-faint">
                  Agreement with independent burned-area mapping. A description, not a pass/fail gate.
                </span>
              </td>
              <td className="px-3 py-2 text-right text-muted tnum">{fmt(audit.burned_area_r2_raw, 3)}</td>
              <td className="px-3 py-2 text-right text-muted tnum">{fmt(audit.burned_area_r2_harm, 3)}</td>
              <td className="px-3 py-2">
                <Status state={r2Available ? "descriptive" : "na"} />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-faint">
        Industrial filter: {audit.industrial_false_positives_removed.toLocaleString("en-US")} detection
        {audit.industrial_false_positives_removed === 1 ? "" : "s"} discarded (Shannon temporal entropy H &gt; 0.75)
        {audit.industrial_false_positives_removed === 0
          ? " — no flaring detected in this area with the current pipeline."
          : "."} Peak drift: {fmt(audit.phenology_shift_days_per_decade)} days per decade; Mann–Kendall p ={" "}
        {fmtP(audit.mann_kendall_p_value)}.
      </p>
    </section>
  );
}
