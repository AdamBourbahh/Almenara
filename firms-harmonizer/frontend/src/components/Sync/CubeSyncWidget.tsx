import { useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { useAnalysisStore } from "../../store/useAnalysisStore";

const coverageFormat = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeZone: "UTC"
});

export function CubeSyncWidget() {
  const { coverageDateEnd, syncSource, syncStatus, syncError, fetchSyncStatus, triggerSync } =
    useAnalysisStore(useShallow((state) => ({
      coverageDateEnd: state.coverageDateEnd,
      syncSource: state.syncSource,
      syncStatus: state.syncStatus,
      syncError: state.syncError,
      fetchSyncStatus: state.fetchSyncStatus,
      triggerSync: state.triggerSync
    })));

  useEffect(() => {
    void fetchSyncStatus();
    const timer = window.setInterval(() => void fetchSyncStatus(), 60_000);
    return () => window.clearInterval(timer);
  }, [fetchSyncStatus]);

  const updating = syncStatus === "in_progress";
  return (
    <section aria-label="FIRMS data coverage" className="relative flex items-center gap-2 rounded border border-rule bg-paper px-2 py-1 text-xs">
      <p aria-live="polite" className="leading-tight text-muted">
        <span className="block">{syncSource === "synthetic" ? "Synthetic data through" : "FIRMS data through"}</span>
        {coverageDateEnd ? (
          <time className="font-medium text-ink" dateTime={coverageDateEnd}>
            {coverageFormat.format(new Date(`${coverageDateEnd}T00:00:00Z`))}
          </time>
        ) : <span>Unavailable</span>}
      </p>
      <button
        type="button"
        disabled={updating || syncSource === "synthetic"}
        title={syncSource === "synthetic" ? "FIRMS updates are unavailable in synthetic mode" : "Fetch the latest available observations from NASA FIRMS"}
        onClick={() => void triggerSync()}
        className="flex shrink-0 items-center gap-1 border border-rule px-2 py-1.5 text-ink hover:bg-panel focus-visible:outline-2 focus-visible:outline-reference disabled:opacity-50"
      >
        <RefreshCw aria-hidden="true" className={`h-3.5 w-3.5 ${updating ? "motion-safe:animate-spin" : ""}`} />
        {updating ? "Updating…" : "Update through today"}
      </button>
      {syncError && <p role="status" className="absolute right-0 top-full z-10 mt-2 w-56 rounded border border-rule bg-paper p-2 text-terracotta shadow-sm">{syncError}</p>}
    </section>
  );
}
