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
  Flame,
  BookOpen,
  Satellite,
  Trash2,
  Radio,
  ArrowRight
} from "lucide-react";
import { useAnalysisStore } from "../../store/useAnalysisStore";
import type { CitationReference } from "../../api/types";

// ============================================================================
// Markdown & Inline Formatting Helpers
// ============================================================================

function parseInlineFormatting(text: string, citations: CitationReference[] = []): React.ReactNode[] {
  // Regex matches:
  // 1. Markdown links: [label](url)
  // 2. Bold text: **bold**
  // 3. Inline code: `code`
  // 4. Citation pills: [1]..[99] or [W1]..[W99]
  const pattern = /(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`|\[(?:W\d+|\d+)\])/g;
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
    const citMatch = part.match(/^\[(W\d+|\d+)\]$/);
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
    if (line.startsWith("### ")) {
      elements.push(
        <h4 key={idx} className="mt-3.5 mb-1.5 font-serif text-base font-semibold text-ink">
          {parseInlineFormatting(line.slice(4), citations)}
        </h4>
      );
    } else if (line.startsWith("#### ")) {
      elements.push(
        <h5 key={idx} className="mt-2.5 mb-1 text-xs font-semibold uppercase tracking-wider text-faint">
          {parseInlineFormatting(line.slice(5), citations)}
        </h5>
      );
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      elements.push(
        <li key={idx} className="ml-4 list-disc text-xs leading-relaxed text-muted">
          {parseInlineFormatting(line.slice(2), citations)}
        </li>
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
    ? "Web Report"
    : isNasa
    ? "NASA Dataset"
    : "Peer-Reviewed";

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
// Main Fire Copilot Drawer Component
// ============================================================================

export function FireCopilotDrawer() {
  const {
    isCopilotOpen,
    copilotLoading,
    copilotError,
    copilotMessages,
    activeSpikeDay,
    activeSpikeHex,
    closeCopilot,
    askCopilot,
    clearCopilotMessages,
    openCopilot
  } = useAnalysisStore(
    useShallow((s) => ({
      isCopilotOpen: s.isCopilotOpen,
      copilotLoading: s.copilotLoading,
      copilotError: s.copilotError,
      copilotMessages: s.copilotMessages,
      activeSpikeDay: s.activeSpikeDay,
      activeSpikeHex: s.activeSpikeHex,
      closeCopilot: s.closeCopilot,
      askCopilot: s.askCopilot,
      clearCopilotMessages: s.clearCopilotMessages,
      openCopilot: s.openCopilot
    }))
  );

  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

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

  return (
    <>
      {/* Backdrop overlay */}
      <div
        className="fixed inset-0 z-40 bg-ink/20 backdrop-blur-[2px] transition-opacity lg:hidden"
        onClick={closeCopilot}
        aria-hidden="true"
      />

      {/* Slide-over Drawer */}
      <aside
        aria-label="Fire AI Copilot"
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-rule bg-panel shadow-2xl transition-transform lg:top-16"
      >
        {/* Header */}
        <header className="flex shrink-0 items-center justify-between border-b border-rule px-4 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-md bg-reference/10 text-reference border border-reference/20">
              <Sparkles className="h-4 w-4" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-serif text-base font-semibold text-ink">Fire AI Copilot</h3>
                <span className="inline-flex items-center gap-1 rounded-full bg-validated/10 px-2 py-0.5 text-[10px] font-medium text-validated border border-validated/25">
                  <Radio className="h-2.5 w-2.5 animate-pulse" />
                  Evidence first
                </span>
              </div>
              <p className="text-[11px] text-faint">
                Explore satellite detections and attributed fire reports
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1">
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

        {/* Active Telemetry Chip */}
        {(activeSpikeDay || activeSpikeHex) && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule bg-paper/50 px-4 py-2 text-xs">
            <div className="flex items-center gap-1.5 text-muted">
              <Flame className="h-3.5 w-3.5 text-terracotta" />
              <span className="font-medium text-ink">Active Context:</span>
              {activeSpikeDay && (
                <span>
                  {activeSpikeDay.date} · {activeSpikeDay.harmonized_fre_mj_km2.toFixed(1)} MJ/km² · Anomaly{" "}
                  {activeSpikeDay.z_score_anomaly.toFixed(2)}σ
                </span>
              )}
              {!activeSpikeDay && activeSpikeHex && (
                <span className="font-mono text-[11px]">
                  Hex {activeSpikeHex.h3_index.slice(0, 10)}… (Entropy: {activeSpikeHex.shannon_entropy.toFixed(2)})
                </span>
              )}
            </div>

            <button
              type="button"
              onClick={() => openCopilot({ day: activeSpikeDay, hex: activeSpikeHex })}
              className="text-[11px] font-medium text-reference hover:underline"
            >
              Re-analyze
            </button>
          </div>
        )}

        {/* Message Thread */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4 space-y-4">
          {copilotMessages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center p-6">
              <div className="flex h-12 w-12 items-center justify-center rounded-full bg-reference/10 text-reference border border-reference/20 mb-3">
                <Sparkles className="h-6 w-6" />
              </div>
              <h4 className="font-serif text-lg font-semibold text-ink">
                Investigate a fire
              </h4>
              <p className="mt-1.5 max-w-sm text-xs leading-relaxed text-muted">
                Ask about a place and date, or inspect the selected map area. Answers distinguish
                satellite detections, reported events and what remains unknown. Follow-up questions keep the conversation context.
              </p>

              <div className="mt-6 w-full space-y-2 text-left">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-faint">
                  Suggested inquiries:
                </p>
                {[
                  "What happened near Madrid on 24 July 2026?",
                  "Investigate the fires near Careiro, Amazonas on 13 September 2024.",
                  "Which days had the most detections near Manaus in September 2024?",
                  "Can satellite FRP tell us the cause or burned area?"
                ].map((q, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => handleQuickQuestion(q)}
                    className="group flex w-full items-center justify-between rounded border border-rule bg-panel px-3 py-2 text-xs text-muted hover:border-reference hover:bg-paper hover:text-ink transition-colors"
                  >
                    <span>{q}</span>
                    <ArrowRight className="h-3 w-3 text-faint group-hover:text-reference transition-colors" />
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
                  </div>
                ) : (
                  <div className="w-full rounded-lg border border-rule bg-panel p-3.5 shadow-sm">
                    {/* Assistant Metadata Badges */}
                    <div className="mb-2.5 flex flex-wrap items-center gap-1.5 border-b border-rule pb-2">
                      <span className="flex items-center gap-1 font-serif text-xs font-semibold text-ink">
                        <Bot className="h-3.5 w-3.5 text-reference" />
                        FIRMS AI
                      </span>

                      {/* Provider Badge */}
                      {msg.response?.model_used && (
                        <span className="rounded border border-rule bg-paper px-1.5 py-0.5 font-mono text-[10px] text-faint">
                          {msg.response.model_used.startsWith("deterministic") ? "Local evidence" : "AI assisted"}
                        </span>
                      )}

                      {/* Physical Classification Badge */}
                      {msg.response?.physical_classification && (
                        <span className="rounded border border-rule px-1.5 py-0.5 font-mono text-[10px] text-muted">
                          {msg.response.physical_classification.replaceAll("_", " ").toLowerCase()}
                        </span>
                      )}

                      {/* Web results retrieved Badge */}
                      {msg.response?.web_search_used && (
                        <span className="inline-flex items-center gap-1 rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
                          <Globe className="h-3 w-3" />
                          Web results retrieved
                        </span>
                      )}
                    </div>

                    {/* Executed Search Query in Muted Monospace Text */}
                    {msg.response?.web_search_used && msg.response.search_query_executed && (
                      <div className="mb-2 rounded bg-paper/80 px-2.5 py-1.5 border border-rule/60">
                        <p className="font-mono text-[11px] text-faint truncate">
                          <span className="text-muted font-sans font-medium">Executed Search:</span>{" "}
                          "{msg.response.search_query_executed}"
                        </p>
                      </div>
                    )}

                    {msg.response?.data_source === "synthetic" && (
                      <p className="mb-2 text-xs font-medium text-bias">Synthetic demo data · cannot verify real fires</p>
                    )}
                    {/* Markdown Body */}
                    <div className="text-xs text-ink">{renderMarkdownBlocks(msg.content, msg.response?.citations)}</div>

                    {/* Verifiable References List */}
                    {msg.response?.citations && msg.response.citations.length > 0 && (
                      <div className="mt-4 border-t border-rule pt-3">
                        <div className="mb-2 flex items-center justify-between">
                          <h5 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-faint">
                            <ShieldCheck className="h-3.5 w-3.5 text-validated" />
                            Sources ({msg.response.citations.length})
                          </h5>
                          <span className="text-[10px] text-faint">Open a source to check its scope</span>
                        </div>

                        <ul className="space-y-2">
                          {msg.response.citations.map((cit, idx) => (
                            <CitationCard key={cit.id || idx} citation={cit} />
                          ))}
                        </ul>
                      </div>
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
          <form onSubmit={handleSubmit} className="flex items-center gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about a place, date or follow-up…"
              disabled={copilotLoading}
              maxLength={6000}
              aria-label="Question for Fire Copilot"
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
