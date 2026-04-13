"use client";
/**
 * app/pipeline/page.tsx - Pipeline control panel.
 * Trigger a run, watch live status, see last result.
 */
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, PipelineStatus, ApiError } from "@/lib/api";
import ErrorBanner from "@/components/ErrorBanner";
import { relativeTime } from "@/lib/utils";

const STATUS_COLOUR: Record<string, string> = {
  idle:      "text-gray-400",
  running:   "text-yellow-400",
  succeeded: "text-green-400",
  failed:    "text-red-400",
};

const STATUS_ICON: Record<string, string> = {
  idle:      "⏳",
  running:   "🏃",
  succeeded: "✅",
  failed:    "❌",
};

// -- Stage progress bar ---------------------------------------------------
const STAGES = ["extraction", "neo4j_load", "resolution", "erp_load", "geo_enrichment", "done"];

function StageBar({ current }: { current: string }) {
  const idx = STAGES.indexOf(current);
  return (
    <div className="flex gap-1 items-center">
      {STAGES.slice(0, -1).map((s, i) => (
        <div key={s} className="flex items-center gap-1">
          <div
            className={`h-2 w-16 rounded-full transition-colors ${
              i < idx ? "bg-green-500" :
              i === idx ? "bg-yellow-400 animate-pulse" :
              "bg-gray-700"
            }`}
          />
          {i < STAGES.length - 2 && (
            <div className="w-1 h-1 rounded-full bg-gray-700" />
          )}
        </div>
      ))}
    </div>
  );
}

// -- Toggle option --------------------------------------------------------
function Toggle({ label, checked, onChange, description }: {
  label: string; checked: boolean; onChange: (v: boolean) => void; description?: string;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer group">
      <div className="relative mt-0.5">
        <input
          type="checkbox"
          checked={checked}
          onChange={e => onChange(e.target.checked)}
          className="sr-only"
        />
        <div className={`w-10 h-5 rounded-full transition-colors ${checked ? "bg-brand-600" : "bg-gray-700"}`} />
        <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
          checked ? "translate-x-5" : "translate-x-0.5"
        }`} />
      </div>
      <div>
        <p className="text-sm font-medium text-gray-200">{label}</p>
        {description && <p className="text-xs text-gray-500 mt-0.5">{description}</p>}
      </div>
    </label>
  );
}

// -- Main page ------------------------------------------------------------
export default function PipelinePage() {
  const queryClient = useQueryClient();

  const [opts, setOpts] = useState({
    skip_extract: false,
    skip_neo4j:   false,
    skip_erp:     false,
    skip_geo:     false,
    skip_resolve: false,
  });

  // Poll status every 3s when running
  const statusQ = useQuery({
    queryKey: ["pipelineStatus"],
    queryFn:  api.getPipelineStatus,
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? 3000 : false,
  });

  const resultQ = useQuery({
    queryKey: ["pipelineResult"],
    queryFn:  api.getLastPipelineResult,
    enabled:  statusQ.data?.status !== "running",
  });

  const triggerMutation = useMutation({
    mutationFn: () => api.triggerPipeline(opts),
    onSuccess: () => {
      // Start polling immediately
      queryClient.invalidateQueries({ queryKey: ["pipelineStatus"] });
    },
  });

  // Refresh result when run finishes
  useEffect(() => {
    if (statusQ.data?.status === "succeeded" || statusQ.data?.status === "failed") {
      queryClient.invalidateQueries({ queryKey: ["pipelineResult"] });
      // Refresh graph data
      queryClient.invalidateQueries({ queryKey: ["summary"] });
      queryClient.invalidateQueries({ queryKey: ["emissions"] });
    }
  }, [statusQ.data?.status, queryClient]);

  const status       = statusQ.data;
  const isRunning    = status?.status === "running";
  const triggerError = triggerMutation.error;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Pipeline Control</h1>
        <p className="text-gray-400 text-sm mt-1">
          Run the full extraction + Neo4j ingestion pipeline
        </p>
      </div>

      {statusQ.error && <ErrorBanner error={statusQ.error} onRetry={statusQ.refetch} />}

      <div className="grid md:grid-cols-2 gap-6">

        {/* Trigger card */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-5">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Configure Run</h2>
          
          <div className="space-y-4">
            <Toggle
              label="Skip LLM Extraction"
              description="Re-use existing triple files from data/triples/"
              checked={opts.skip_extract}
              onChange={v => setOpts(o => ({ ...o, skip_extract: v }))}
            />
            <Toggle
              label="Skip Neo4j Load"
              description="Don't write to the graph database"
              checked={opts.skip_neo4j}
              onChange={v => setOpts(o => ({ ...o, skip_neo4j: v }))}
            />
            <Toggle
              label="Skip Entity Resolution"
              description="Skip fuzzy deduplication of company names"
              checked={opts.skip_resolve}
              onChange={v => setOpts(o => ({ ...o, skip_resolve: v }))}
            />
            <Toggle
              label="Skip ERP Load"
              description="Don't load mock supplier data"
              checked={opts.skip_erp}
              onChange={v => setOpts(o => ({ ...o, skip_erp: v }))}
            />
            <Toggle
              label="Skip Geo Enrichment"
              description="Don't geocode Region / Facility nodes"
              checked={opts.skip_geo}
              onChange={v => setOpts(o => ({ ...o, skip_geo: v }))}
            />
          </div>

          {triggerError && (
            <ErrorBanner
              error={triggerError}
            />
          )}

          <button
            onClick={() => triggerMutation.mutate()}
            disabled={isRunning || triggerMutation.isPending}
            className={`w-full py-2.5 rounded-lg font-semibold text-sm transition-colors ${
              isRunning || triggerMutation.isPending
                ? "bg-gray-700 text-gray-500 cursor-not-allowed"
                : "bg-brand-600 hover:bg-brand-700 text-white"
            }`}
          >
            {isRunning ? "Pipeline running..." : "▶ Run Pipeline"}
          </button>
        </div>

        {/* Status card */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-4">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Status</h2>

          {status ? (
            <>
              <div className="flex items-center gap-3">
                <span className="text-2xl">{STATUS_ICON[status.status]}</span>
                <div>
                  <p className={`font-bold text-lg ${STATUS_COLOUR[status.status]}`}>
                    {status.status.toUpperCase()}
                  </p>
                  {status.stage && status.status === "running" && (
                    <p className="text-gray-400 text-xs capitalize">
                      Current stage: <span className="text-yellow-300">{status.stage.replace("_", " ")}</span>
                    </p>
                  )}
                </div>
              </div>

              {status.status === "running" && (
                <StageBar current={status.stage} />
              )}

              <div className="text-xs text-gray-500 space-y-0.5">
                {status.started && <p>Started: {relativeTime(status.started)}</p>}
                {status.finished && <p>Finished: {relativeTime(status.finished)}</p>}
              </div>

              {status.errors.length > 0 && (
                <div className="bg-red-950/50 border border-red-800/50 rounded-lg p-3">
                  <p className="text-red-400 text-xs font-semibold mb-1">Errors / Warnings</p>
                  {status.errors.map((e, i) => (
                    <p key={i} className="text-red-300 text-xs font-mono">{e}</p>
                  ))}
                </div>
              )}
            </>
          ) : (
            <p className="text-gray-600 text-sm">No run data yet.</p>
          )}
        </div>
      </div>

      {/* Last result */}
      {resultQ.data && resultQ.data.result && Object.keys(resultQ.data.result).length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wide mb-4">Last Run Result</h2>
          <pre className="text-xs text-gray-400 font-mono bg-gray-950 rounded-lg p-4 overflow-x-auto">
            {JSON.stringify(resultQ.data.result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}