import { useCallback, useRef, useState } from "react";
import { analyzeTrip, ApiError, fetchHeatmap, isAbort } from "../api/client";
import type { AnalyzeRequest, AnalyzeResponse, HeatmapResponse } from "../api/types";

export type AnalysisStatus = "idle" | "loading" | "success" | "error";

export interface HeatState {
  status: "idle" | "loading" | "ready" | "error";
  data?: HeatmapResponse;
  error?: ApiError;
}

const toApiError = (e: unknown) =>
  e instanceof ApiError ? e : new ApiError("unknown", "Something went wrong. Please try again.");

/**
 * Owns the data flow: analyze the trip, then (automatically) load the 0-48 h heatmap for
 * the returned corridor. Stale responses from superseded requests are ignored.
 */
export function useTrip() {
  const [status, setStatus] = useState<AnalysisStatus>("idle");
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [heat, setHeat] = useState<HeatState>({ status: "idle" });

  const runId = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const loadHeatmap = useCallback(async (a: AnalyzeResponse, id: number, signal: AbortSignal) => {
    setHeat({ status: "loading" });
    try {
      const data = await fetchHeatmap(
        { points: a.corridor, start: a.request.departure, load_lb: a.request.load_lb },
        signal,
      );
      if (id === runId.current) setHeat({ status: "ready", data });
    } catch (e) {
      if (isAbort(e) || id !== runId.current) return;
      setHeat({ status: "error", error: toApiError(e) });
    }
  }, []);

  const analyze = useCallback(
    async (payload: AnalyzeRequest) => {
      controller.current?.abort();
      const ctrl = new AbortController();
      controller.current = ctrl;
      const id = ++runId.current;

      setStatus("loading");
      setError(null);
      setAnalysis(null);
      setSelectedId(null);
      setHeat({ status: "idle" });
      try {
        const result = await analyzeTrip(payload, ctrl.signal);
        if (id !== runId.current) return;
        setAnalysis(result);
        setSelectedId(result.recommended_route_id);
        setStatus("success");
        void loadHeatmap(result, id, ctrl.signal);
      } catch (e) {
        if (isAbort(e) || id !== runId.current) return;
        setError(toApiError(e));
        setStatus("error");
      }
    },
    [loadHeatmap],
  );

  const retryHeatmap = useCallback(() => {
    if (!analysis) return;
    controller.current?.abort();
    const ctrl = new AbortController();
    controller.current = ctrl;
    void loadHeatmap(analysis, runId.current, ctrl.signal);
  }, [analysis, loadHeatmap]);

  return { status, analysis, error, selectedId, setSelectedId, heat, analyze, retryHeatmap };
}
