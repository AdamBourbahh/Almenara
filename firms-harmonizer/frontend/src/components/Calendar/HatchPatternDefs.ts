/**
 * Crea un patrón diagonal (Hatched Pattern) fuera de pantalla para representar
 * días con gap-filling (RTS Kalman) o predicción operativa de 14 días.
 */
export function createHatchPattern(
  ctx: CanvasRenderingContext2D,
  lineColor: string = "rgba(255, 255, 255, 0.4)",
  bgColor: string = "rgba(15, 23, 42, 0.8)"
): CanvasPattern | null {
  const patternCanvas = document.createElement("canvas");
  patternCanvas.width = 8;
  patternCanvas.height = 8;
  const pCtx = patternCanvas.getContext("2d");

  if (!pCtx) return null;

  // Fondo de la celda con trama
  pCtx.fillStyle = bgColor;
  pCtx.fillRect(0, 0, 8, 8);

  // Dibujar líneas diagonales
  pCtx.strokeStyle = lineColor;
  pCtx.lineWidth = 1.5;
  pCtx.beginPath();
  pCtx.moveTo(0, 8);
  pCtx.lineTo(8, 0);
  pCtx.moveTo(-2, 2);
  pCtx.lineTo(2, -2);
  pCtx.moveTo(6, 10);
  pCtx.lineTo(10, 6);
  pCtx.stroke();

  return ctx.createPattern(patternCanvas, "repeat");
}

export type HatchKind = "gapFilled" | "forecast";

const HATCH_LINE_COLOR: Record<HatchKind, string> = {
  gapFilled: "rgba(224, 242, 254, 0.55)", // Kalman / cross-guard gap filling
  forecast: "rgba(251, 191, 36, 0.8)" // 14-day operational forecast (gold)
};

const patternCache = new WeakMap<CanvasRenderingContext2D, Map<HatchKind, CanvasPattern | null>>();

/** Transparent-background hatch overlay for the calendar canvas, created once per context and kind. */
export function getHatchPattern(ctx: CanvasRenderingContext2D, kind: HatchKind): CanvasPattern | null {
  let byKind = patternCache.get(ctx);
  if (!byKind) {
    byKind = new Map();
    patternCache.set(ctx, byKind);
  }
  if (!byKind.has(kind)) byKind.set(kind, createHatchPattern(ctx, HATCH_LINE_COLOR[kind], "rgba(0, 0, 0, 0)"));
  return byKind.get(kind) ?? null;
}

/** CSS equivalent of the canvas hatch, for legend swatches. */
export function hatchCss(kind: HatchKind): string {
  const color = HATCH_LINE_COLOR[kind];
  return `repeating-linear-gradient(135deg, ${color} 0 1.5px, transparent 1.5px 4px)`;
}
