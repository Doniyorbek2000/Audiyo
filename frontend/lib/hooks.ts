"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, eventsUrl } from "./api";
import type { PipelineEvent } from "./types";

/** GET soʻrovi + qayta yuklash. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));

  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { data, setData, error, loading, reload };
}

/** Konveyer hodisalari (SSE). Uzilishda brauzer avtomatik qayta ulanadi. */
export function usePipelineEvents(
  kind: "projects" | "books",
  id: string | null,
  onEvent: (e: PipelineEvent) => void,
) {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (!id) return;
    const source = new EventSource(eventsUrl(kind, id));
    const listen = (e: MessageEvent) => {
      try {
        handler.current(JSON.parse(e.data) as PipelineEvent);
      } catch {
        /* notoʻgʻri JSON */
      }
    };
    for (const t of ["snapshot", "status", "progress", "segment", "block", "cost", "error"]) {
      source.addEventListener(t, listen as EventListener);
    }
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, [kind, id]);

  return connected;
}
