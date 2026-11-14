/**
 * Diagonal hatch patterns (8 × 8 px off-screen tile + ctx.createPattern) used by the
 * Burning Calendar to mark:
 *  - gap-filled days (RTS Kalman / historical cross-guard): white/cyan stripes
 *  - 14-day operational forecast days: golden stripes
 *
 * Tiles and patterns are cached, so redrawing the calendar never allocates new canvases.
 */

export const HATCH_TILE_SIZE = 8;

export const HATCH_STYLES = {
  gapFilled: { lineColor: "rgba(29, 78, 216, 0.85)", bgColor: "rgba(29, 78, 216, 0.08)" },
  forecast: { lineColor: "rgba(180, 83, 9, 0.9)", bgColor: "rgba(180, 83, 9, 0.10)" }
} as const;

export type HatchStyleName = keyof typeof HATCH_STYLES;

const tileCache = new Map<string, HTMLCanvasElement>();
const patternCache = new WeakMap<CanvasRenderingContext2D, Map<string, CanvasPattern>>();

function buildTile(lineColor: string, bgColor: string): HTMLCanvasElement | null {
  const tile = document.createElement("canvas");
  tile.width = HATCH_TILE_SIZE;
  tile.height = HATCH_TILE_SIZE;
  const pCtx = tile.getContext("2d");
  if (!pCtx) return null;

  const s = HATCH_TILE_SIZE;
  if (bgColor !== "transparent") {
    pCtx.fillStyle = bgColor;
    pCtx.fillRect(0, 0, s, s);
  }

  // Main diagonal + the two corner segments so stripes stay continuous across tiles.
  pCtx.strokeStyle = lineColor;
  pCtx.lineWidth = 1.5;
  pCtx.lineCap = "square";
  pCtx.beginPath();
  pCtx.moveTo(0, s);
  pCtx.lineTo(s, 0);
  pCtx.moveTo(-s / 4, s / 4);
  pCtx.lineTo(s / 4, -s / 4);
  pCtx.moveTo(s - s / 4, s + s / 4);
  pCtx.lineTo(s + s / 4, s - s / 4);
  pCtx.stroke();

  return tile;
}

export function createHatchPattern(
  ctx: CanvasRenderingContext2D,
  lineColor: string = "rgba(255, 255, 255, 0.4)",
  bgColor: string = "transparent"
): CanvasPattern | null {
  const key = `${lineColor}|${bgColor}`;

  let perContext = patternCache.get(ctx);
  const cached = perContext?.get(key);
  if (cached) return cached;

  let tile = tileCache.get(key);
  if (!tile) {
    const built = buildTile(lineColor, bgColor);
    if (!built) return null;
    tile = built;
    tileCache.set(key, tile);
  }

  const pattern = ctx.createPattern(tile, "repeat");
  if (!pattern) return null;
  if (!perContext) {
    perContext = new Map();
    patternCache.set(ctx, perContext);
  }
  perContext.set(key, pattern);
  return pattern;
}

export function getHatchPattern(ctx: CanvasRenderingContext2D, style: HatchStyleName): CanvasPattern | null {
  const { lineColor, bgColor } = HATCH_STYLES[style];
  return createHatchPattern(ctx, lineColor, bgColor);
}

/** CSS equivalent for HTML legends (keeps legend and canvas visually identical). */
export function hatchCss(style: HatchStyleName): string {
  const { lineColor, bgColor } = HATCH_STYLES[style];
  return `repeating-linear-gradient(-45deg, ${lineColor} 0 1.5px, ${bgColor} 1.5px ${HATCH_TILE_SIZE / Math.SQRT2}px)`;
}
