import { useEffect, useState } from "react";
import { fetchObservations, type Observations } from "../api/client";
import { useAnalysisStore } from "../store/useAnalysisStore";

/** Uncalibrated FIRMS records remain available alongside the temporal energy map. */
export function ObservationsPage() {
  const aoi = useAnalysisStore((s) => s.currentAoi);
  const [data, setData] = useState<Observations | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(null);
    fetchObservations(aoi, controller.signal).then((result) => {
      if (!controller.signal.aborted) setData(result);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Observations unavailable");
    });
    return () => controller.abort();
  }, [aoi]);
  function exportCsv() {
    if (!data) return;
    const rows = ["date,detection_count,summed_instantaneous_frp_mw,sensors,data_source",
      ...data.daily.map((d) => `${d.date},${d.detection_count},${d.raw_frp_mw},${d.sensors.join("|")},real`)];
    const url = URL.createObjectURL(new Blob([rows.join("\r\n")], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a"); a.href = url; a.download = "FIRMS_observations.csv"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="h-full overflow-auto p-6 text-ink">
    <div className="flex items-center justify-between gap-3">
      <h1 className="font-serif text-xl">Real FIRMS observations</h1>
      <button onClick={exportCsv} disabled={!data} className="border border-rule px-3 py-2 text-xs disabled:opacity-40">Export observations CSV</button>
    </div>
    {error ? <p role="alert">{error}</p> : !data ? <p role="status">Loading real observations…</p> : <>
      <p className="my-3 text-sm">{data.total_detections.toLocaleString("en-US")} satellite detections · {data.first_observed_date}–{data.last_observed_date}</p>
      <p className="mb-4 text-xs text-muted">{data.method}</p>
      <table className="w-full text-left text-xs"><thead><tr><th>Date</th><th>Detections</th><th>Summed instantaneous FRP (MW)</th><th>Sensors</th></tr></thead>
        <tbody>{data.daily.map((d) => <tr key={d.date} className="border-t border-rule"><td className="py-2"><button className="text-reference underline" onClick={() => useAnalysisStore.getState().setSelectedDate(d.date)}>{d.date}</button></td><td>{d.detection_count}</td><td>{d.raw_frp_mw.toFixed(2)}</td><td>{d.sensors.join(", ")}</td></tr>)}</tbody>
      </table>
    </>}
  </section>;
}
