import { PRESET_REGIONS, useAnalysisStore } from "../../store/useAnalysisStore";
export function MapInfo() {
  const data = useAnalysisStore((s) => s.observationData);
  const selected = useAnalysisStore((s) => s.selectedPreset);
  return <section className="space-y-3 p-4 text-xs text-muted">
    <h3 className="font-serif text-lg text-ink">{PRESET_REGIONS[selected]?.label ?? "Selected area"}</h3>
    <p>Accepted NASA FIRMS detections from MODIS and VIIRS. Exact archive/NRT duplicates are removed. Standard coordinate, date and quality checks apply.</p>
    <dl className="grid grid-cols-2 gap-2"><dt>Detections</dt><dd>{data?.total_detections.toLocaleString("en-US") ?? "—"}</dd><dt>First detection</dt><dd>{data?.first_observed_date ?? "—"}</dd><dt>Last detection</dt><dd>{data?.last_observed_date ?? "—"}</dd><dt>Cells with detections</dt><dd>{data?.map_hexagons.length.toLocaleString("en-US") ?? "—"}</dd></dl>
    <p>Map color and height show detection counts over the full available period. These counts depend on sensor sensitivity and sampling.</p>
    <p>FRP is instantaneous radiative power in MW. Summing detections does not measure burned energy, fire duration or burned area.</p>
    <p>No gap filling or forecast is used. Missing detections do not establish that no fire occurred. Basemap imagery requires a connection; the coordinate grid remains available offline.</p>
  </section>;
}
