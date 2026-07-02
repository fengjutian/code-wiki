import { useEffect, useRef } from "react";
import { useConfigStore } from "@/store/configStore";
import type { AnalysisStatus } from "@/lib/types";

function snakeToCamel(raw: Record<string, unknown>): Partial<AnalysisStatus> {
  const data: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(raw)) {
    const camelKey = k.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
    data[camelKey] = v;
  }
  return data as unknown as Partial<AnalysisStatus>;
}

export function useSSE() {
  const setAnalysisStatus = useConfigStore((s) => s.setAnalysisStatus);
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let retries = 0;
    let cancelled = false;
    const maxRetries = 10;

    function connect() {
      if (cancelled) return;
      const es = new EventSource("/api/events");
      eventSourceRef.current = es;

      es.addEventListener("progress", (e) => {
        try {
          const raw = JSON.parse(e.data);
          const data = snakeToCamel(raw);
          setAnalysisStatus(data);
          if (data.status === "done" || data.status === "error") {
            useConfigStore.getState().fetchWikiTree();
            useConfigStore.getState().fetchFileTree();
            es.close();
          }
        } catch { /* ignore parse errors */ }
      });

      es.addEventListener("file-change", (e) => {
        try {
          const data = JSON.parse(e.data);
          console.log("File change detected:", data.files);
          useConfigStore.getState().fetchWikiTree();
        } catch { /* ignore */ }
      });

      es.onerror = () => {
        es.close();
        if (!cancelled && retries < maxRetries) {
          retries++;
          retryRef.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      cancelled = true;
      eventSourceRef.current?.close();
      clearTimeout(retryRef.current);
    };
  }, [setAnalysisStatus]);
}
