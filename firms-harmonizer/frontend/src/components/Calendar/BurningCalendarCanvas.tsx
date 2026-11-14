import { useEffect, useMemo, useRef, useState } from "react";
import { useAnalysisStore } from "../../store/useAnalysisStore";

export function BurningCalendarCanvas() {
  const data = useAnalysisStore((s) => s.observationData);
  const selectedYear = useAnalysisStore((s) => s.selectedYear);
  const setYear = useAnalysisStore((s) => s.setSelectedYear);
  const canvas = useRef<HTMLCanvasElement>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [hover, setHover] = useState("Hover a day to inspect its observations.");
  const days = useMemo(() => new Map((data?.daily ?? []).map((d) => [d.date,d])), [data]);
  const years = useMemo(() => {
    if (!data?.daily.length) return [];
    const first = data.daily[0].year, last = data.daily[data.daily.length-1].year;
    return Array.from({length:last-first+1},(_,i) => first+i);
  },[data]);
  const rowH=20, left=44, height=years.length*rowH+30;
  useEffect(() => {
    if (!wrapper.current) return;
    const observer=new ResizeObserver(([e])=>setWidth(Math.max(370,e.contentRect.width)));
    observer.observe(wrapper.current); return ()=>observer.disconnect();
  },[]);
  useEffect(() => {
    const node=canvas.current; if (!node) return;
    const ratio=window.devicePixelRatio || 1; node.width=width*ratio; node.height=height*ratio;
    const ctx=node.getContext("2d"); if (!ctx) return;
    ctx.scale(ratio,ratio); ctx.clearRect(0,0,width,height);
    const cellW=(width-left)/366;
    const max=Math.max(1,...(data?.daily ?? []).map((d)=>d.detection_count));
    ctx.font="10px sans-serif";
    years.forEach((year,row)=>{
      ctx.fillStyle="#64748b";ctx.fillText(String(year),2,row*rowH+14);
      const length=(Date.UTC(year+1,0,1)-Date.UTC(year,0,1))/86400000;
      for(let day=0;day<length;day++){
        const iso=new Date(Date.UTC(year,0,day+1)).toISOString().slice(0,10);
        const value=days.get(iso); const t=value ? Math.log1p(value.detection_count)/Math.log1p(max) : 0;
        ctx.fillStyle=value ? `rgb(${254-75*t},${210-210*t},${150-150*t})` : "#e5e7eb";
        ctx.fillRect(left+day*cellW,row*rowH,Math.max(1,cellW),rowH-2);
      }
    });
    ctx.fillStyle="#64748b";ctx.fillText("Jan",left,height-7);ctx.fillText("Jul",left+182*cellW,height-7);ctx.fillText("Dec",width-25,height-7);
  },[data,days,years,width,height]);
  const selected=(data?.daily ?? []).filter((d)=>d.year===selectedYear);
  return <div ref={wrapper} className="space-y-4">
    <div className="overflow-x-auto"><canvas ref={canvas} style={{width,height}} aria-label="Daily satellite detection counts by year. Grey days have no reported detections." onPointerMove={(event)=>{
      const rect=event.currentTarget.getBoundingClientRect();const row=Math.floor((event.clientY-rect.top)/rowH);const day=Math.floor((event.clientX-rect.left-left)/((width-left)/366));
      if(row<0||row>=years.length||day<0||day>=366)return;
      const date=new Date(Date.UTC(years[row],0,day+1)); if(date.getUTCFullYear()!==years[row])return;
      const iso=date.toISOString().slice(0,10), value=days.get(iso);
      setHover(value ? `${iso}: ${value.detection_count.toLocaleString("en-US")} detections; summed instantaneous FRP ${value.raw_frp_mw.toFixed(2)} MW; ${value.sensors.join(", ")}.` : `${iso}: no reported detections; coverage unknown.`);
    }} onClick={(event)=>{
      const rect=event.currentTarget.getBoundingClientRect();const row=Math.floor((event.clientY-rect.top)/rowH);const day=Math.floor((event.clientX-rect.left-left)/((width-left)/366));
      if(row<0||row>=years.length||day<0||day>=366)return;
      const date=new Date(Date.UTC(years[row],0,day+1)); if(date.getUTCFullYear()!==years[row])return;
      const iso=date.toISOString().slice(0,10), value=days.get(iso);
      if (value) {
        useAnalysisStore.getState().openCopilot({
          day: {
            date: iso,
            year: value.year,
            doy: value.doy,
            raw_hotspot_count: value.detection_count,
            raw_frp_mw: value.raw_frp_mw,
            harmonized_fre_mj_km2: value.raw_frp_mw * 0.01,
            historical_cross_prior_fre: 0,
            ci_95_lower: 0,
            ci_95_upper: 0,
            uncertainty_pct: 10,
            biomass_burned_tonnes: value.raw_frp_mw * 0.368,
            pm25_emitted_kg: null,
            z_score_anomaly: 1.0,
            is_gap_filled: false,
            is_forecast: false,
            gap_reason: null,
            active_sensors: value.sensors,
            tooltip_narrative: null
          }
        });
      }
    }} /></div>
    <p role="status" className="min-h-10 text-sm text-muted">{hover}</p>
    <label className="flex items-center gap-3 text-sm">Inspect year <select aria-label="Inspect observation year" value={selectedYear} onChange={(e)=>setYear(Number(e.target.value))} className="border border-rule bg-paper p-2">{years.map((y)=><option key={y}>{y}</option>)}</select></label>
    <p className="text-sm text-muted">{selected.length} days with reported detections in {selectedYear}. Showing the first 100 rows; CSV includes the full record.</p>
    <table className="w-full text-left text-xs"><thead><tr className="border-b border-rule"><th className="p-2">UTC date</th><th>Detections</th><th>Summed FRP (MW)</th><th>Sensors</th></tr></thead><tbody>{selected.slice(0,100).map((d)=><tr key={d.date} className="border-b border-rule"><td className="p-2">{d.date}</td><td>{d.detection_count}</td><td>{d.raw_frp_mw.toFixed(2)}</td><td>{d.sensors.join(", ")}</td></tr>)}</tbody></table>
  </div>;
}
