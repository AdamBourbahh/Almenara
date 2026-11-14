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
  pCtx.moveTo(6, 10);
  pCtx.lineTo(10, 6);
  pCtx.stroke();

  return ctx.createPattern(patternCanvas, "repeat");
}
