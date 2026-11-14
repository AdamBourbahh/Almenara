export function RampLegend({
  label,
  stops,
  low,
  high,
}: {
  label: string;
  stops: string[];
  low: string;
  high: string;
}) {
  const gradient = `linear-gradient(90deg, ${stops.join(", ")})`;
  return (
    <div className="glass rounded-xl px-3 py-2.5">
      <p className="mb-2 text-[10px] font-medium uppercase tracking-wide text-dim">
        {label}
      </p>
      <div className="h-2 w-44 rounded-full" style={{ background: gradient }} />
      <div className="mt-1.5 flex items-center justify-between text-[10px] text-dim">
        <span>{low}</span>
        <span>{high}</span>
      </div>
    </div>
  );
}
