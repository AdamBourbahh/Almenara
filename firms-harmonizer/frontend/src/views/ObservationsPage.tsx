import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Loader2 } from "lucide-react";
import { fetchObservations, type Observations } from "../api/client";
import { useAnalysisStore } from "../store/useAnalysisStore";
import { PageShell } from "./PageShell";

const PAGE_DAYS = 200;
const number = new Intl.NumberFormat("en-US");
const power = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const dayFormat = new Intl.DateTimeFormat("en-US", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

function formatDay(iso: string | null): string {
  return iso ? dayFormat.format(new Date(`${iso}T00:00:00Z`)) : "—";
}

function Stat({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <div className="px-4 py-3">
      <p className="text-[11px] text-faint">{label}</p>
      <p className="mt-0.5 font-serif text-xl text-ink tnum">{value}</p>
      {detail && <p className="mt-0.5 text-[11px] text-faint">{detail}</p>}
    </div>
  );
}

/** Uncalibrated FIRMS records remain available alongside the temporal energy map. */
export function ObservationsPage() {
  const aoi = useAnalysisStore((s) => s.currentAoi);
  const selectedDate = useAnalysisStore((s) => s.selectedDate);
  // Page 0 is the most recent stretch of days: what people look for first.
  const [page, setPage] = useState(0);
  const [totalDays, setTotalDays] = useState<number | null>(null);
  const [data, setData] = useState<Observations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => { setPage(0); setTotalDays(null); setData(null); }, [aoi]);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    const load = async () => {
      // The server pages from the oldest day, so the total is needed to address the newest.
      const total = totalDays ?? (await fetchObservations(aoi, controller.signal, 0, 1)).total_days;
      if (controller.signal.aborted) return;
      if (totalDays === null) { setTotalDays(total); return; }
      const end = Math.max(0, total - page * PAGE_DAYS);
      const start = Math.max(0, end - PAGE_DAYS);
      const result = await fetchObservations(aoi, controller.signal, start, Math.max(1, end - start));
      if (!controller.signal.aborted) setData(result);
    };
    load().catch((err: unknown) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Observations unavailable");
    });
    return () => controller.abort();
  }, [aoi, page, totalDays]);

  const rows = useMemo(() => (data ? [...data.daily].reverse() : []), [data]);
  const busiest = useMemo(() => rows.reduce((max, d) => Math.max(max, d.detection_count), 1), [rows]);
  const pages = Math.max(1, Math.ceil((totalDays ?? 0) / PAGE_DAYS));
  const loadingPage = !error && (!data || data.offset !== Math.max(0, Math.max(0, (totalDays ?? 0) - page * PAGE_DAYS) - PAGE_DAYS));

  async function exportCsv() {
    if (!data) return;
    setExporting(true);
    try {
      const daily: Observations["daily"] = [];
      for (let offset = 0; offset < data.total_days; offset += 1000) {
        const batch = await fetchObservations(aoi, undefined, offset, 1000);
        daily.push(...batch.daily);
      }
      const lines = ["date,detection_count,summed_instantaneous_frp_mw,sensors,data_source",
        ...daily.map((d) => `${d.date},${d.detection_count},${d.raw_frp_mw},${d.sensors.join("|")},real`)];
      const url = URL.createObjectURL(new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = url; link.download = "FIRMS_observations.csv"; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "CSV export failed");
    } finally {
      setExporting(false);
    }
  }

  return (
    <PageShell
      eyebrow="Raw record"
      title="Satellite detections, day by day"
      intro="The untouched FIRMS record behind every chart: accepted detections per day, before harmonization. Pick a date to show that day on the map and timeline."
    >
      <section className="border border-rule bg-panel p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-faint">Real FIRMS observations</p>
            <h3 className="mt-1 font-serif text-xl text-ink">Daily detections in the selected area</h3>
          </div>
          <button
            type="button"
            onClick={exportCsv}
            disabled={!data || exporting}
            className="flex shrink-0 items-center gap-2 border border-ink/20 px-3 py-2 text-xs font-medium text-ink hover:bg-paper disabled:opacity-40"
          >
            {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
            {exporting ? "Preparing CSV…" : "Export all days (CSV)"}
          </button>
        </div>

        {error ? (
          <p role="alert" className="mt-5 border border-bias/40 bg-bias/10 p-3 text-sm text-bias">{error}</p>
        ) : !data ? (
          <p role="status" className="mt-5 flex items-center gap-2 text-sm text-muted">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading real observations…
          </p>
        ) : (
          <>
            <div className="mt-5 grid grid-cols-1 divide-y divide-rule border border-rule sm:grid-cols-3 sm:divide-x sm:divide-y-0">
              <Stat label="Satellite detections" value={number.format(data.total_detections)} detail="Pixels flagged as hot, not separate fires" />
              <Stat label="Days with detections" value={number.format(data.total_days)} detail="Days without a row have no reported detection" />
              <Stat label="Record" value={`${formatDay(data.first_observed_date)} – ${formatDay(data.last_observed_date)}`} />
            </div>
            <p className="mt-3 max-w-3xl text-xs leading-relaxed text-muted">{data.method}</p>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 text-xs">
              <p className="text-muted" aria-live="polite">
                {rows.length > 0 ? <>Showing <span className="text-ink">{formatDay(rows[0].date)}</span> back to <span className="text-ink">{formatDay(rows[rows.length - 1].date)}</span></> : "No days on this page"}
                {loadingPage && <Loader2 className="ml-2 inline h-3 w-3 animate-spin" />}
              </p>
              <div className="flex items-center gap-2">
                <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}
                  className="flex items-center gap-1 border border-rule px-2.5 py-1.5 text-ink hover:bg-paper disabled:opacity-40">
                  <ChevronLeft className="h-3.5 w-3.5" /> Newer
                </button>
                <span className="tnum text-muted">Page {page + 1} of {pages}</span>
                <button type="button" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}
                  className="flex items-center gap-1 border border-rule px-2.5 py-1.5 text-ink hover:bg-paper disabled:opacity-40">
                  Older <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            <div className="mt-3 max-h-[560px] overflow-auto border border-rule">
              <table className="w-full min-w-[620px] border-collapse text-left text-xs">
                <thead className="sticky top-0 z-10 bg-paper text-faint">
                  <tr className="border-b border-rule">
                    <th className="px-3 py-2 font-medium">Date (UTC)</th>
                    <th className="px-3 py-2 text-right font-medium">Detections</th>
                    <th className="w-[28%] px-3 py-2 font-medium"><span className="sr-only">Share of the busiest day on this page</span></th>
                    <th className="px-3 py-2 text-right font-medium" title="Instantaneous fire radiative power summed over the day's detections. It is not energy.">Summed FRP (MW)</th>
                    <th className="px-3 py-2 font-medium">Sensors</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {rows.map((d) => {
                    const active = d.date === selectedDate;
                    return (
                      <tr key={d.date} className={active ? "bg-reference/10" : "hover:bg-paper/60"}>
                        <td className="px-3 py-1.5">
                          <button type="button" aria-pressed={active} title="Show this day on the map and timeline"
                            onClick={() => useAnalysisStore.getState().setSelectedDate(d.date)}
                            className={`tnum underline-offset-2 hover:underline ${active ? "font-semibold text-reference" : "text-reference"}`}>
                            {formatDay(d.date)}
                          </button>
                        </td>
                        <td className="px-3 py-1.5 text-right text-ink tnum">{number.format(d.detection_count)}</td>
                        <td className="px-3 py-1.5" aria-hidden="true">
                          <span className="block h-1.5 rounded-full bg-terracotta/70" style={{ width: `${Math.max(2, (d.detection_count / busiest) * 100)}%` }} />
                        </td>
                        <td className="px-3 py-1.5 text-right text-muted tnum">{power.format(d.raw_frp_mw)}</td>
                        <td className="px-3 py-1.5 text-muted">{d.sensors.join(" · ")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {selectedDate && rows.some((d) => d.date === selectedDate) && (
              <p className="mt-2 text-[11px] text-faint">{formatDay(selectedDate)} is selected: the map and timeline now show that day.</p>
            )}
          </>
        )}
      </section>
    </PageShell>
  );
}
