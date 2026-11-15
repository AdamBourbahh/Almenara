import React, { useEffect, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import {
  ExternalLink,
  Globe,
  Sparkles,
  X,
  Send,
  Bot,
  ShieldCheck,
  BookOpen,
  Satellite,
  Trash2,
  Radio,
  ArrowRight,
  Calculator,
  Database,
  ShieldAlert,
  Square,
  Volume2
} from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import type { CitationReference, CopilotEvidenceSource, ExplainSpikeResponse } from "../../api/types";
import { CopilotContextPanel } from "./CopilotContextPanel";
import { calculationItems, evidenceBadges, refusalBody, starterPrompts } from "./copilotPresentation";

// ============================================================================
// Markdown & Inline Formatting Helpers
// ============================================================================

function parseInlineFormatting(text: string, citations: CitationReference[] = []): React.ReactNode[] {
  // Regex matches:
  // 1. Markdown links: [label](url)
  // 2. Bold text: **bold**
  // 3. Inline code: `code`
  // 4. Citation pills: [1]..[99] or [W1]..[W99]
  const pattern = /(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`|\[(?:[A-Z]*\d+(?:_\d+)?)\])/g;
  const parts = text.split(pattern);

  return parts.map((part, i) => {
    if (!part) return null;

    // Link: [label](url)
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      const [, label, url] = linkMatch;
      if (!/^https?:\/\//i.test(url)) return label;
      return (
        <a
          key={i}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-0.5 font-medium text-reference underline decoration-reference/40 underline-offset-2 hover:decoration-reference"
        >
          <span>{label}</span>
          <ExternalLink className="inline h-2.5 w-2.5 opacity-70" />
        </a>
      );
    }

    // Bold: **text**
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-ink">
          {part.slice(2, -2)}
        </strong>
      );
    }

    // Inline code: `code`
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={i}
          className="rounded border border-rule bg-paper px-1 py-0.5 font-mono text-[11px] text-ink"
        >
          {part.slice(1, -1)}
        </code>
      );
    }

    // Citation badge: [1] or [W1]
    const citMatch = part.match(/^\[([A-Z]*\d+(?:_\d+)?)\]$/);
    if (citMatch) {
      const id = citMatch[1];
      const isWeb = id.startsWith("W");
      const source = citations.find((citation) => citation.id === `[${id}]`);
      if (!source?.url || !/^https?:\/\//i.test(source.url)) return part;
      return (
        <a
          key={i}
          href={source.url}
          title={source.title}
          target="_blank"
          rel="noopener noreferrer"
          className={`inline-block mx-0.5 rounded px-1 py-0.2 text-[10px] font-mono font-medium ${
            isWeb
              ? "bg-sky-500/15 text-sky-600 dark:text-sky-400 border border-sky-500/30"
              : "bg-amber-500/15 text-amber-700 dark:text-amber-400 border border-amber-500/30"
          }`}
        >
          [{id}]
        </a>
      );
    }

    return part;
  });
}

function renderMarkdownBlocks(content: string, citations: CitationReference[] = []): React.ReactNode {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let inTable = false;
  let tableRows: string[][] = [];
  let listItems: string[] = [];
  const flushList = (key: number) => {
    if (!listItems.length) return;
    elements.push(<ul key={`list-${key}`} className="ml-4 list-disc space-y-1 text-xs leading-relaxed text-muted">
      {listItems.map((item, index) => <li key={index}>{parseInlineFormatting(item, citations)}</li>)}
    </ul>);
    listItems = [];
  };

  const flushTable = (key: number) => {
    if (tableRows.length === 0) return;
    const header = tableRows[0];
    const dataRows = tableRows.slice(2); // Skip separator row

    elements.push(
      <div key={`table-${key}`} className="my-2.5 overflow-x-auto border border-rule">
        <table className="w-full min-w-[320px] border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-rule bg-paper/60">
              {header.map((col, idx) => (
                <th key={idx} className="px-2.5 py-1.5 font-medium text-faint">
                  {col.trim()}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-rule font-mono">
            {dataRows.map((row, rIdx) => (
              <tr key={rIdx} className="hover:bg-paper/30">
                {row.map((val, cIdx) => (
                  <td key={cIdx} className="px-2.5 py-1.5 text-muted">
                    {parseInlineFormatting(val.trim(), citations)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
    tableRows = [];
    inTable = false;
  };

  for (let idx = 0; idx < lines.length; idx++) {
    const rawLine = lines[idx];
    const line = rawLine.trim();

    if (line.startsWith("- ") || line.startsWith("* ")) {
      if (inTable) flushTable(idx);
      listItems.push(line.slice(2));
      continue;
    }
    flushList(idx);

    // Table row detection
    if (line.startsWith("|") && line.endsWith("|")) {
      inTable = true;
      const cols = line
        .slice(1, -1)
        .split("|")
        .map((c) => c.trim());
      tableRows.push(cols);
      continue;
    } else if (inTable) {
      flushTable(idx);
    }

    if (!line) continue;

    // Headers
    if (/^#{1,3} /.test(line)) {
      elements.push(
        <h4 key={idx} className="mt-3.5 mb-1.5 font-serif text-base font-semibold text-ink">
          {parseInlineFormatting(line.replace(/^#{1,3} /, ""), citations)}
        </h4>
      );
    } else if (line.startsWith("#### ")) {
      elements.push(
        <h5 key={idx} className="mt-2.5 mb-1 text-xs font-semibold uppercase tracking-wider text-faint">
          {parseInlineFormatting(line.slice(5), citations)}
        </h5>
      );
    } else {
      elements.push(
        <p key={idx} className="my-1.5 text-xs leading-relaxed text-muted">
          {parseInlineFormatting(line, citations)}
        </p>
      );
    }
  }

  if (inTable) flushTable(lines.length);
  flushList(lines.length);

  return <div className="space-y-1">{elements}</div>;
}

// ============================================================================
// Verifiable Reference Card Component
// ============================================================================

interface CitationCardProps {
  citation: CitationReference;
}

const CitationCard: React.FC<CitationCardProps> = ({ citation }) => {
  const isWeb = citation.source_type === "WEB_NEWS_REPORT";
  const isNasa = citation.source_type === "NASA_DATASET";

  // Badge styling per source type:
  // - WEB_NEWS_REPORT: Sky blue
  // - NASA_DATASET: Purple / Indigo
  // - PEER_REVIEWED: Amber / Gold
  const badgeClasses = isWeb
    ? "border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400"
    : isNasa
    ? "border-purple-500/30 bg-purple-500/10 text-purple-600 dark:text-purple-400"
    : "border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400";

  const sourceLabel = isWeb
    ? citation.dataset_or_doi.startsWith("Official") ? "Official report" : "News report"
    : isNasa
    ? "NASA Dataset"
    : "Scientific literature";

  const SourceIcon = isWeb ? Globe : isNasa ? Satellite : BookOpen;

  return (
    <li className="rounded border border-rule bg-paper/60 p-2.5 transition-colors hover:border-rule-strong">
      <div className="flex flex-wrap items-center justify-between gap-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-semibold text-ink">{citation.id}</span>
          <span
            className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${badgeClasses}`}
          >
            <SourceIcon className="h-2.5 w-2.5" />
            {sourceLabel}
          </span>
        </div>
        <span className="font-mono text-[10px] text-faint">
          {citation.authors_or_agency} · {citation.dataset_or_doi.includes("unverified") ? "publication date unverified" : citation.year}
        </span>
      </div>

      <div className="mt-1.5">
        {citation.url ? (
          <a
            href={citation.url}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-1 font-medium text-xs text-ink hover:text-reference hover:underline"
            title={`Open external source: ${citation.url}`}
          >
            <span>{citation.title}</span>
            <ExternalLink className="h-3 w-3 shrink-0 text-faint transition-colors group-hover:text-reference" />
          </a>
        ) : (
          <span className="font-medium text-xs text-ink">{citation.title}</span>
        )}
      </div>

      {citation.relevance_note && (
        <p className="mt-1 text-[11px] leading-relaxed text-muted">{citation.relevance_note}</p>
      )}

      {citation.dataset_or_doi && (
        <p className="mt-1 text-[10px] font-mono text-faint truncate">
          Identifier: {citation.dataset_or_doi}
        </p>
      )}
    </li>
  );
};

// ============================================================================
// Provenance Badges & Verified Calculation Card
// ============================================================================

const BADGE_STYLE: Record<CopilotEvidenceSource, { icon: typeof Database; className: string }> = {
  local_cube: { icon: Database, className: "border-reference/30 bg-reference/10 text-reference" },
  verified_calculation: { icon: Calculator, className: "border-validated/30 bg-validated/10 text-validated" },
  web: { icon: Globe, className: "border-terracotta/30 bg-terracotta/10 text-terracotta" },
  knowledge: { icon: BookOpen, className: "border-rule-strong bg-paper text-muted" },
  guardrail: { icon: ShieldAlert, className: "border-bias/30 bg-bias/10 text-bias" }
};

function EvidenceBadges({ response }: { response: ExplainSpikeResponse | undefined }) {
  const badges = evidenceBadges(response);
  if (!badges.length) return null;
  return (
    <ul aria-label="How this answer was produced" className="flex flex-wrap items-center gap-1.5">
      {badges.map((badge) => {
        const { icon: Icon, className } = BADGE_STYLE[badge.kind];
        return (
          <li
            key={badge.kind}
            title={badge.detail}
            className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium leading-4 ${className}`}
          >
            <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span>{badge.label}</span>
            <span className="sr-only">: {badge.detail}</span>
          </li>
        );
      })}
    </ul>
  );
}

function VerifiedCalculationCard({ response }: { response: ExplainSpikeResponse | undefined }) {
  const items = calculationItems(response);
  if (!items.length) return null;
  const note = response?.verified_calculations?.note;
  return (
    <details className="group mt-3 rounded border border-validated/25 bg-validated/5">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded px-3 py-2 text-xs font-semibold text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-reference [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-1.5">
          <Calculator className="h-3.5 w-3.5 text-validated" aria-hidden="true" />
          Verified calculation
          <span className="font-normal text-faint">
            · {items.length} {items.length === 1 ? "formula" : "formulas"}
          </span>
        </span>
        <ArrowRight className="h-3 w-3 text-faint transition-transform duration-150 ease-out group-open:rotate-90 motion-reduce:transition-none" aria-hidden="true" />
      </summary>
      <div className="border-t border-validated/20 px-3 py-2.5">
        <dl className="space-y-2">
          {items.map((item, index) => (
            <div key={`${item.label}-${index}`}>
              <dt className="text-[11px] font-medium text-muted">{item.label}</dt>
              <dd className="mt-0.5 overflow-x-auto whitespace-nowrap font-mono text-[11px] tabular-nums text-ink">{item.formula}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2.5 text-[10px] leading-relaxed text-faint">
          Computed by the server from the local record, not by the language model.{note ? ` ${note}` : ""}
        </p>
      </div>
    </details>
  );
}

// ============================================================================
// Read-aloud (browser Web Speech API: offline, no backend, no API key)
// ============================================================================

const SPEECH_RATES = [1, 1.5, 2] as const;

function speechChunks(markdown: string): string[] {
  return markdown
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("|"))
    .map((line) =>
      line
        .replace(/^[-*]\s+/, "")
        .replace(/^#{1,6}\s+/, "")
        .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
        .replace(/\[(?:[A-Z]*\d+(?:_\d+)?)\]/g, "")
        .replace(/[*`]/g, "")
        .trim()
    )
    .flatMap((line) => line.split(/(?<=[.!?])\s+/))
    .filter(Boolean);
}

// The Copilot answers in English: always use an English voice. First choice is
// Chrome's "Google US English" (the Google Translate voice), then Edge's
// "Natural" neural voices, then any other en-US / en-GB voice.
function englishVoiceScore(voice: SpeechSynthesisVoice): number {
  const lang = voice.lang.toLowerCase().replace("_", "-");
  if (!lang.startsWith("en")) return -1;
  let score = 0;
  if (voice.name === "Google US English") score += 16;
  else if (/google/i.test(voice.name)) score += 10;
  if (/natural|neural|online/i.test(voice.name)) score += 8;
  if (lang === "en-us") score += 2;
  else if (lang === "en-gb") score += 1;
  if (voice.localService) score += 0.5;
  return score;
}

function pickEnglishVoice(localOnly = false): SpeechSynthesisVoice | null {
  let best: SpeechSynthesisVoice | null = null;
  let bestScore = -1;
  for (const voice of window.speechSynthesis.getVoices()) {
    if (localOnly && !voice.localService) continue;
    const score = englishVoiceScore(voice);
    if (score > bestScore) {
      best = voice;
      bestScore = score;
    }
  }
  return best;
}

function useReadAloud() {
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [rate, setRate] = useState<number>(1);
  const session = useRef({ token: 0, chunks: [] as string[], index: 0 });
  const voiceRef = useRef<SpeechSynthesisVoice | null>(null);

  // Voices load asynchronously in Chrome/Edge: pick once they are available.
  useEffect(() => {
    if (!supported) return;
    const refresh = () => {
      voiceRef.current = pickEnglishVoice();
    };
    refresh();
    window.speechSynthesis.addEventListener("voiceschanged", refresh);
    return () => window.speechSynthesis.removeEventListener("voiceschanged", refresh);
  }, [supported]);

  const playFrom = (startIndex: number, rateValue: number) => {
    const current = session.current;
    const token = ++current.token;
    window.speechSynthesis.cancel();
    const speakChunk = (index: number) => {
      if (token !== current.token) return;
      if (index >= current.chunks.length) {
        setSpeakingId(null);
        return;
      }
      current.index = index;
      const utterance = new SpeechSynthesisUtterance(current.chunks[index]);
      utterance.rate = rateValue;
      const voice = voiceRef.current ?? pickEnglishVoice();
      if (voice) utterance.voice = voice;
      utterance.lang = voice?.lang ?? "en-US";
      utterance.onend = () => speakChunk(index + 1);
      utterance.onerror = () => {
        if (token !== current.token) return;
        // Online voices (Google / Edge Natural) fail without internet:
        // switch to an installed offline English voice and retry the sentence.
        if (voice && !voice.localService) {
          voiceRef.current = pickEnglishVoice(true);
          speakChunk(index);
          return;
        }
        setSpeakingId(null);
      };
      window.speechSynthesis.speak(utterance);
    };
    speakChunk(startIndex);
  };

  const stop = () => {
    if (!supported) return;
    session.current.token += 1;
    window.speechSynthesis.cancel();
    setSpeakingId(null);
  };

  const toggle = (id: string, markdown: string) => {
    if (!supported) return;
    if (speakingId === id) {
      stop();
      return;
    }
    const chunks = speechChunks(markdown);
    if (!chunks.length) return;
    session.current.chunks = chunks;
    setSpeakingId(id);
    playFrom(0, rate);
  };

  // Speed changes apply immediately: restart from the sentence being read.
  const cycleRate = () => {
    const next = SPEECH_RATES[(SPEECH_RATES.indexOf(rate as (typeof SPEECH_RATES)[number]) + 1) % SPEECH_RATES.length];
    setRate(next);
    if (supported && speakingId) playFrom(session.current.index, next);
  };

  return { supported, speakingId, rate, toggle, stop, cycleRate };
}

// ============================================================================
// Main FIRMS Copilot Drawer Component
// ============================================================================

export function FireCopilotDrawer() {
  const {
    isCopilotOpen,
    copilotLoading,
    copilotError,
    copilotMessages,
    copilotContext,
    closeCopilot,
    askCopilot,
    clearCopilotMessages
  } = useAnalysisStore(
    useShallow((s) => ({
      isCopilotOpen: s.isCopilotOpen,
      copilotLoading: s.copilotLoading,
      copilotError: s.copilotError,
      copilotMessages: s.copilotMessages,
      copilotContext: s.copilotContext,
      closeCopilot: s.closeCopilot,
      askCopilot: s.askCopilot,
      clearCopilotMessages: s.clearCopilotMessages
    }))
  );

  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const speech = useReadAloud();
  const stopSpeech = speech.stop;
  const hasMessages = copilotMessages.length > 0;

  // Silence playback when the drawer closes, the chat is cleared, or on unmount.
  useEffect(() => {
    if (!isCopilotOpen || !hasMessages) stopSpeech();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isCopilotOpen, hasMessages]);
  useEffect(() => () => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  useEffect(() => {
    if (isCopilotOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [isCopilotOpen, copilotMessages, copilotLoading]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || copilotLoading) return;
    const query = input;
    setInput("");
    void askCopilot(query);
  };

  const handleQuickQuestion = (q: string) => {
    if (copilotLoading) return;
    void askCopilot(q);
  };

  if (!isCopilotOpen) return null;

  const starters = starterPrompts(copilotContext);

  return (
    <>
      {/* Backdrop overlay */}
      <div
        className="absolute inset-0 z-30 bg-ink/20 backdrop-blur-[2px] transition-opacity lg:hidden"
        onClick={closeCopilot}
        aria-hidden="true"
      />

      {/* Slide-over Drawer */}
      <aside
        aria-label="FIRMS Copilot"
        className="absolute inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-rule bg-panel shadow-2xl transition-transform"
      >
        {/* Header */}
        <header className="flex shrink-0 items-center justify-between border-b border-rule px-4 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-reference/10 text-reference border border-reference/20">
              <Sparkles className="h-4 w-4" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-serif text-base font-semibold text-ink">FIRMS Copilot</h3>
                <span className="inline-flex items-center gap-1 rounded-full bg-validated/10 px-2 py-0.5 text-[10px] font-medium text-validated border border-validated/25">
                  <Radio className="h-2.5 w-2.5 animate-pulse" />
                  Evidence first
                </span>
              </div>
              <p className="text-[11px] text-faint">
                Query local energy, satellite detections and fire reports
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1">
            {speech.supported && (
              <button
                type="button"
                onClick={speech.cycleRate}
                className="rounded border border-rule px-1.5 py-1 font-mono text-[11px] tabular-nums text-muted hover:bg-paper hover:text-ink transition-colors"
                title="Read-aloud speed (click to change)"
                aria-label={`Read-aloud speed ${speech.rate}x. Click to change.`}
              >
                {speech.rate}x
              </button>
            )}
            {copilotMessages.length > 0 && (
              <button
                type="button"
                onClick={clearCopilotMessages}
                className="rounded p-1.5 text-faint hover:bg-paper hover:text-ink transition-colors"
                title="Clear chat history"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            )}
            <button
              type="button"
              onClick={closeCopilot}
              className="rounded p-1.5 text-muted hover:bg-paper hover:text-ink transition-colors"
              title="Close Copilot"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        {/* Message Thread */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4 space-y-4">
          {copilotMessages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center p-6">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-reference/10 text-reference border border-reference/20 mb-3">
                <Sparkles className="h-6 w-6" />
              </div>
              <h4 className="font-serif text-lg font-semibold text-ink">
                Explore your FIRMS data
              </h4>
              <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-muted">
                Ask about a place and date, or inspect the selected map area. Answers distinguish
                satellite detections, reported events and what remains unknown. Follow-up questions keep the conversation context.
              </p>

              <div className="mt-6 w-full space-y-2 text-left">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-faint">
                  Suggested inquiries
                </p>
                {starters.caption && (
                  <p className="break-words text-[11px] text-muted">For {starters.caption}</p>
                )}
                {starters.prompts.map((q) => (
                  <button
                    key={q}
                    type="button"
                    disabled={copilotLoading}
                    onClick={() => handleQuickQuestion(q)}
                    className="group flex min-h-10 w-full items-center justify-between gap-3 rounded border border-rule bg-panel px-3 py-2 text-left text-xs text-muted transition-colors duration-150 ease-out hover:border-reference hover:bg-paper hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-reference active:scale-[0.99] disabled:opacity-50 motion-reduce:transition-none motion-reduce:active:scale-100"
                  >
                    <span>{q}</span>
                    <ArrowRight className="h-3 w-3 shrink-0 text-faint transition-colors duration-150 group-hover:text-reference" aria-hidden="true" />
                  </button>
                ))}
              </div>
            </div>
          ) : (
            copilotMessages.map((msg) => (
              <div
                key={msg.id}
                className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
              >
                {msg.role === "user" ? (
                  <div className="max-w-[85%] rounded-lg bg-ink px-3.5 py-2.5 text-xs text-paper">
                    <p className="leading-relaxed">{msg.content}</p>
                    {msg.context && <p className="mt-1 text-[10px] opacity-75">{msg.context.hex ? `H3 ${msg.context.hex.h3_index}` : msg.context.label} · {msg.context.start}–{msg.context.end}</p>}
                  </div>
                ) : (
                  <div className="w-full rounded-lg border border-rule bg-panel p-3.5 shadow-sm">
                    {/* Assistant Metadata Badges */}
                    <div className="mb-2.5 flex flex-wrap items-center gap-1.5 border-b border-rule pb-2">
                      <span className="flex items-center gap-1 font-serif text-xs font-semibold text-ink">
                        <Bot className="h-3.5 w-3.5 text-reference" />
                        FIRMS Copilot
                      </span>

                      {/* Provider Badge */}
                      {msg.response?.model_used && !msg.response.guardrail_triggered && (
                        <span className="rounded border border-rule bg-paper px-1.5 py-0.5 font-mono text-[10px] text-faint">
                          {/^(deterministic|offline)/.test(msg.response.model_used) ? "Local evidence" : "AI assisted"}
                        </span>
                      )}

                      {/* Provenance: which evidence this answer rests on */}
                      <EvidenceBadges response={msg.response} />

                      {speech.supported && (
                        <button
                          type="button"
                          onClick={() =>
                            speech.toggle(
                              msg.id,
                              msg.response?.guardrail_triggered ? refusalBody(msg.content, msg.response.suggested_prompts) : msg.content
                            )
                          }
                          className={`ml-auto inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
                            speech.speakingId === msg.id
                              ? "border-reference bg-reference/10 text-reference"
                              : "border-rule text-muted hover:border-reference hover:text-ink"
                          }`}
                          title={speech.speakingId === msg.id ? "Stop reading" : "Read this answer aloud"}
                          aria-pressed={speech.speakingId === msg.id}
                        >
                          {speech.speakingId === msg.id ? (
                            <Square className="h-3 w-3" aria-hidden="true" />
                          ) : (
                            <Volume2 className="h-3 w-3" aria-hidden="true" />
                          )}
                          {speech.speakingId === msg.id ? "Stop" : "Listen"}
                        </button>
                      )}
                    </div>

                    {msg.response?.data_source === "synthetic" && (
                      <p className="mb-2 text-xs font-medium text-bias">Synthetic demo data · cannot verify real fires</p>
                    )}
                    {msg.response?.map_context && (
                      <p className="mb-2 text-[11px] text-faint">
                        Queried: {msg.response.map_context.label} · {msg.response.map_context.period_start}–{msg.response.map_context.period_end}
                      </p>
                    )}
                    {/* Markdown Body */}
                    <div className="text-[13px] text-ink">
                      {renderMarkdownBlocks(
                        msg.response?.guardrail_triggered ? refusalBody(msg.content, msg.response.suggested_prompts) : msg.content,
                        msg.response?.citations
                      )}
                    </div>

                    {/* Questions offered after a declined request */}
                    {msg.response?.guardrail_triggered && (msg.response.suggested_prompts?.length ?? 0) > 0 && (
                      <div className="mt-3 space-y-1.5">
                        <p className="text-[11px] font-medium text-faint">Questions I can answer here</p>
                        {msg.response.suggested_prompts!.map((q) => (
                          <button
                            key={q}
                            type="button"
                            disabled={copilotLoading}
                            onClick={() => handleQuickQuestion(q)}
                            className="group flex min-h-9 w-full items-center justify-between gap-3 rounded border border-rule bg-paper/60 px-2.5 py-1.5 text-left text-xs text-muted transition-colors duration-150 ease-out hover:border-reference hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-reference disabled:opacity-50 motion-reduce:transition-none"
                          >
                            <span>{q}</span>
                            <ArrowRight className="h-3 w-3 shrink-0 text-faint transition-colors duration-150 group-hover:text-reference" aria-hidden="true" />
                          </button>
                        ))}
                      </div>
                    )}

                    {/* Exact server formulas behind the figures above */}
                    <VerifiedCalculationCard response={msg.response} />

                    {/* Verifiable References List */}
                    {msg.response?.citations && msg.response.citations.length > 0 && (
                      <details className="mt-4 border-t border-rule pt-3">
                        <summary className="mb-2 flex cursor-pointer items-center justify-between">
                          <h5 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-faint">
                            <ShieldCheck className="h-3.5 w-3.5 text-validated" />
                            Sources ({msg.response.citations.length})
                          </h5>
                          <span className="text-[10px] text-faint">View evidence</span>
                        </summary>

                        <ul className="space-y-2">
                          {msg.response.citations.map((cit, idx) => (
                            <CitationCard key={cit.id || idx} citation={cit} />
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                )}
              </div>
            ))
          )}

          {copilotLoading && (
            <div className="flex items-center gap-2 rounded border border-rule bg-panel p-3 text-xs text-muted">
              <Sparkles className="h-4 w-4 animate-spin text-reference" />
              <span>Checking local observations and relevant reports…</span>
            </div>
          )}

          {copilotError && (
            <div className="rounded border border-bias/40 bg-bias/10 p-3 text-xs text-bias">
              <p className="font-medium">Error running copilot</p>
              <p className="mt-0.5">{copilotError}</p>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar */}
        <footer className="shrink-0 border-t border-rule bg-panel p-3.5">
          <CopilotContextPanel />
          <form onSubmit={handleSubmit} className="flex items-center gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about a place, date or follow-up…"
              disabled={copilotLoading}
              maxLength={6000}
              aria-label="Question for FIRMS Copilot"
              className="flex-1 rounded border border-rule bg-paper px-3 py-2 text-xs text-ink placeholder:text-faint focus:border-reference focus:outline-none focus:ring-1 focus:ring-reference"
            />
            <button
              type="submit"
              disabled={copilotLoading || !input.trim()}
              className="flex h-8 w-8 items-center justify-center rounded bg-ink text-paper hover:bg-muted disabled:opacity-40 transition-colors"
              title="Send question"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          </form>
        </footer>
      </aside>
    </>
  );
}
