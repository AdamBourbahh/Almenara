import React, { useEffect, useRef, useCallback } from "react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import { createHatchPattern } from "./HatchPatternDefs";

export const BurningCalendarCanvas: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const {
    analysisData,
    viewMode,
    splitCurtainPct,
    setSplitCurtainPct,
    selectedYear,
    setSelectedYear,
    setHoveredDay
  } = useAnalysisStore();

  const startYear = 2001;
  const endYear = 2026;
  const totalYears = endYear - startYear + 1; // 26 años
  const daysInYear = 366;

  // Manejador del renderizado en Canvas 2D
  const renderCalendar = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;

    ctx.clearRect(0, 0, width, height);

    // Configuración de celdas
    const paddingLeft = 50;
    const paddingTop = 30;
    const cellWidth = (width - paddingLeft - 20) / daysInYear;
    const cellHeight = (height - paddingTop - 20) / totalYears;

    // Patrones diagonales
    const hatchKalman = createHatchPattern(ctx, "rgba(56, 189, 248, 0.6)", "rgba(14, 116, 144, 0.3)");
    const hatchForecast = createHatchPattern(ctx, "rgba(251, 191, 36, 0.7)", "rgba(180, 83, 9, 0.4)");

    // Dibujar etiquetas de años en el Eje Y
    ctx.fillStyle = "#94a3b8";
    ctx.font = "10px monospace";
    for (let i = 0; i < totalYears; i++) {
      const year = startYear + i;
      const y = paddingTop + i * cellHeight;
      ctx.fillText(year.toString(), 10, y + cellHeight * 0.75);
    }

    if (!analysisData || !analysisData.calendar_series) {
      // Estado vacío o simulado si no hay datos cargados aún
      ctx.fillStyle = "#1e293b";
      ctx.fillRect(paddingLeft, paddingTop, width - paddingLeft - 20, height - paddingTop - 20);
      return;
    }

    // Índice rápido para búsqueda de celdas
    const cellMap = new Map<string, any>();
    analysisData.calendar_series.forEach((cell) => {
      cellMap.set(`${cell.year}-${cell.doy}`, cell);
    });

    // Pintar la matriz de celdas
    for (let i = 0; i < totalYears; i++) {
      const year = startYear + i;
      const y = paddingTop + i * cellHeight;

      for (let doy = 1; doy <= daysInYear; doy++) {
        const x = paddingLeft + (doy - 1) * cellWidth;
        const cellKey = `${year}-${doy}`;
        const cellData = cellMap.get(cellKey);

        if (!cellData) {
          ctx.fillStyle = "#0f172a";
          ctx.fillRect(x, y, cellWidth - 0.5, cellHeight - 0.5);
          continue;
        }

        // Determinación del valor según la Cortina Interactiva (splitCurtainPct)
        // A la izquierda de la cortina (o en modo RAW) usamos raw_hotspot_count; a la derecha, harmonized_fre_mj_km2
        const curtainXPixel = paddingLeft + (width - paddingLeft - 20) * (splitCurtainPct / 100);
        const isRawSide = x < curtainXPixel || viewMode === "RAW";

        let intensityVal = 0;
        if (isRawSide) {
          intensityVal = Math.min(1, cellData.raw_hotspot_count / 40);
          ctx.fillStyle = `rgba(239, 68, 68, ${Math.max(0.15, intensityVal)})`; // Rojo crudo / artefacto 2012
        } else {
          intensityVal = Math.min(1, cellData.harmonized_fre_mj_km2 / 500);
          ctx.fillStyle = `rgba(30, 144, 255, ${Math.max(0.15, intensityVal)})`; // Cian/Azul armonizado físico
        }

        ctx.fillRect(x, y, cellWidth - 0.5, cellHeight - 0.5);

        // Superponer trama diagonal si el día fue reconstruido (Gap Filling / RTS Kalman)
        if (cellData.is_gap_filled && hatchKalman) {
          ctx.fillStyle = hatchKalman;
          ctx.fillRect(x, y, cellWidth - 0.5, cellHeight - 0.5);
        }
      }
    }

    // Pintar la banda de 14 días de Forecast (en 2026)
    if (analysisData.forecast_series) {
      const forecastYearIdx = endYear - startYear;
      const y = paddingTop + forecastYearIdx * cellHeight;
      analysisData.forecast_series.forEach((fCell, idx) => {
        const doyIdx = 180 + idx; // Posición de muestra en julio 2026
        const x = paddingLeft + doyIdx * cellWidth;
        if (hatchForecast) {
          ctx.fillStyle = hatchForecast;
          ctx.fillRect(x, y, cellWidth * 1.5, cellHeight - 0.5);
        }
      });
    }

    // Dibujar línea vertical divisoria de la Cortina 2012 Time-Machine
    const curtainLineX = paddingLeft + (width - paddingLeft - 20) * (splitCurtainPct / 100);
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(curtainLineX, paddingTop);
    ctx.lineTo(curtainLineX, height - 10);
    ctx.stroke();

    // Marcadores históricos críticos: Enero 2012 (Suomi-NPP) y Agosto 2022 (MODIS Aqua Safe Mode)[cite: 3]
    const x2012 = paddinglerForDate(2012, 1, paddingLeft, cellWidth);
    drawMarkerLine(ctx, x2012, paddingTop, height, "Jan 2012 (Suomi-NPP)", "#f59e0b");

    const x2022 = paddinglerForDate(2022, 225, paddingLeft, cellWidth);
    drawMarkerLine(ctx, x2022, paddingTop, height, "Aug 2022 (Aqua Safe Mode)", "#ef4444");

  }, [analysisData, viewMode, splitCurtainPct]);

  // Auxiliar para calcular la coordenada X de un evento histórico
  function paddinglerForDate(targetYear: number, doy: number, pLeft: number, cWidth: number) {
    const yearIdx = targetYear - startYear;
    return pLeft + (doy - 1) * cWidth;
  }

  function drawMarkerLine(ctx: CanvasRenderingContext2D, x: number, pTop: number, height: number, label: string, color: string) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, pTop);
    ctx.lineTo(x, height - 10);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = color;
    ctx.font = "9px monospace";
    ctx.fillText(label, x + 4, pTop + 10);
  }

  useEffect(() => {
    renderCalendar();
  }, [renderCalendar]);

  // Manejo de interacción de Click y Hover en el Canvas
  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const clickY = e.clientY - rect.top;
    
    const paddingTop = 30;
    const height = canvas.height;
    const cellHeight = (height - paddingTop - 20) / totalYears;
    const rowIdx = Math.floor((clickY - paddingTop) / cellHeight);

    if (rowIdx >= 0 && rowIdx < totalYears) {
      const clickedYear = startYear + rowIdx;
      setSelectedYear(clickedYear);
    }
  };

  const handleCanvasMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const paddingLeft = 50;
    const paddingTop = 30;
    const width = canvas.width;
    const height = canvas.height;
    const cellWidth = (width - paddingLeft - 20) / daysInYear;
    const cellHeight = (height - paddingTop - 20) / totalYears;

    const doy = Math.floor((mouseX - paddingLeft) / cellWidth) + 1;
    const rowIdx = Math.floor((mouseY - paddingTop) / cellHeight);
    const year = startYear + rowIdx;

    if (doy >= 1 && doy <= 366 && rowIdx >= 0 && rowIdx < totalYears) {
      setHoveredDay(`${year} (DOY: ${doy})`);
    } else {
      setHoveredDay(null);
    }
  };

  return (
    <div className="bg-slate-950 p-4 rounded-xl border border-slate-800 shadow-2xl text-slate-200">
      <div className="flex flex-wrap items-center justify-between gap-4 mb-3">
        <div>
          <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
            <span>🔥 Burning Activity Calendar Matrix (2001–2026)</span>
            <span className="text-xs bg-cyan-950 text-cyan-400 px-2 py-0.5 rounded border border-cyan-800 font-mono">
              Selected Year: {selectedYear}
            </span>
          </h3>
          <p className="text-xs text-slate-400">
            Click any row to inspect year. Drag curtain slider to compare Raw vs. Harmonized physics.
          </p>
        </div>

        {/* Deslizador de la Cortina 2012 Time-Machine */}
        <div className="flex items-center gap-2 bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-800 text-xs">
          <span className="font-mono text-cyan-400">2012 Split Curtain:</span>
          <input
            type="range"
            min="0"
            max="100"
            value={splitCurtainPct}
            onChange={(e) => setSplitCurtainPct(Number(e.target.value))}
            className="w-28 accent-cyan-500 cursor-pointer"
          />
          <span className="font-mono text-slate-300 w-8">{splitCurtainPct}%</span>
        </div>
      </div>

      <div className="relative w-full overflow-x-auto">
        <canvas
          ref={canvasRef}
          width={920}
          height={340}
          onClick={handleCanvasClick}
          onMouseMove={handleCanvasMouseMove}
          onMouseLeave={() => setHoveredDay(null)}
          className="w-full h-auto cursor-crosshair rounded-lg border border-slate-800 bg-[#070B14]"
        />
      </div>
    </div>
  );
};
