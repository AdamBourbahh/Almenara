import type { CopilotEvidenceSource, ExplainSpikeResponse, VerifiedCalculationItem } from "../../api/types";

/** Pure presentation logic for the Copilot drawer; no React, no store, no network. */

export interface EvidenceBadge {
  kind: CopilotEvidenceSource;
  label: string;
  /** Plain-language meaning, used as the accessible description and tooltip. */
  detail: string;
}

const ORDER: CopilotEvidenceSource[] = ["guardrail", "local_cube", "verified_calculation", "web", "knowledge"];
const LABELS: Record<CopilotEvidenceSource, [string, string]> = {
  guardrail: ["Topic guardrail", "This question is outside fire, land and satellite topics, so no data was queried."],
  local_cube: ["Local cube", "Answered from the local satellite fire record for the queried area and dates."],
  verified_calculation: ["Verified calculation", "Figures were computed by the server; the formulas are listed below."],
  web: ["Web investigation", "Reports were retrieved from approved official and news sources."],
  knowledge: ["Method notes", "Uses the local scientific method notes and cited literature."]
};

type Provenance = Pick<ExplainSpikeResponse, "citations" | "web_search_used"> &
  Partial<Pick<ExplainSpikeResponse, "evidence_sources" | "guardrail_triggered" | "verified_calculations">>;

/** Provenance badges in a fixed order. Older responses without `evidence_sources` are inferred. */
export function evidenceBadges(response: Provenance | null | undefined): EvidenceBadge[] {
  if (!response) return [];
  let kinds = new Set<CopilotEvidenceSource>(response.evidence_sources ?? []);
  if (response.guardrail_triggered) kinds = new Set(["guardrail"]);
  else if (!kinds.size) {
    const ids = new Set((response.citations ?? []).map((c) => c.id));
    if (ids.has("[5]") || ids.has("[6]")) kinds.add("local_cube");
    if (calculationItems(response).length) kinds.add("local_cube").add("verified_calculation");
    if (response.web_search_used) kinds.add("web");
  }
  const reports = (response.citations ?? []).filter((c) => c.source_type === "WEB_NEWS_REPORT").length;
  return ORDER.filter((kind) => kinds.has(kind)).map((kind) => ({
    kind,
    label: kind === "web" && reports ? `${LABELS.web[0]} · ${reports} ${reports === 1 ? "source" : "sources"}` : LABELS[kind][0],
    detail: LABELS[kind][1]
  }));
}

/** Well-formed calculation rows only; a malformed payload renders nothing instead of breaking the message. */
export function calculationItems(response: Pick<Provenance, "verified_calculations"> | null | undefined): VerifiedCalculationItem[] {
  const items = response?.verified_calculations?.items;
  if (!Array.isArray(items)) return [];
  return items.filter((item): item is VerifiedCalculationItem =>
    Boolean(item) && typeof item.label === "string" && typeof item.formula === "string" && item.formula.trim().length > 0);
}

/** The refusal sentence without its bullet list, which the drawer renders as tappable prompts. */
export function refusalBody(content: string, prompts: readonly string[] | undefined): string {
  if (!prompts?.length) return content;
  const kept = content.split("\n").filter((line) => !prompts.some((prompt) => line.trim() === `- ${prompt}`));
  return kept.join("\n").replace(/\n*Questions I can answer here:\s*$/, "").trim();
}

export interface StarterContext {
  label: string;
  start: string;
  end: string;
}

export interface StarterPrompts {
  /** Region and period the prompts refer to; null when nothing is attached. */
  caption: string | null;
  prompts: string[];
}

const FIRST_YEAR = 2001;
const LAST_YEAR = 2026;

function periodLabel(start: string, end: string): string {
  if (start === end) return start;
  const year = start.slice(0, 4);
  if (year === end.slice(0, 4) && start.endsWith("-01-01") && end.endsWith("-12-31")) return year;
  return `${start} to ${end}`;
}

/** Starter questions for the attached area and period; every one is answerable offline. */
export function starterPrompts(context: StarterContext | null | undefined): StarterPrompts {
  if (!context) {
    return {
      caption: null,
      prompts: [
        "Which days had the most detections near Manaus in September 2024?",
        "What is the difference between FRP and FRE?",
        "How are days hidden by cloud or sensor outages reconstructed?",
        "Can satellite detections tell us the cause or the burned area?"
      ]
    };
  }
  const parsed = Number(context.end.slice(0, 4));
  const latest = Math.min(LAST_YEAR - 1, Math.max(FIRST_YEAR + 4, Number.isFinite(parsed) ? parsed : LAST_YEAR - 1));
  const period = periodLabel(context.start, context.end);
  return {
    caption: `${context.label} · ${period}`,
    prompts: [
      context.start === context.end
        ? `How much fire energy and dry biomass was consumed in this area on ${context.start}?`
        : `Compare biomass consumed in this area between ${latest - 4} and ${latest}`,
      "How much has the annual fire season peak shifted here over the last 20 years?",
      "What were the largest thermal events recorded in this area?",
      "Are the persistent heat detections here vegetative fires or industrial gas flaring?"
    ]
  };
}
