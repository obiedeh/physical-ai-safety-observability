import { useCallback, useEffect, useRef, useState } from "react";
import { apiErrorMessage, type InferenceResult } from "./api";

export interface PollState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

/**
 * Poll an async loader on an interval. `deps` restarts the poll (and clears
 * the current value) when they change; intervalMs <= 0 fetches once.
 */
export function usePoll<T>(
  loader: () => Promise<T>,
  intervalMs: number,
  deps: unknown[] = []
): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;
  const alive = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const next = await loaderRef.current();
      if (!alive.current) return;
      setData(next);
      setError(null);
    } catch (err) {
      if (!alive.current) return;
      setError(apiErrorMessage(err));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    void refresh();
    if (intervalMs <= 0) return () => void (alive.current = false);
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, intervalMs);
    return () => {
      alive.current = false;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, refresh, ...deps]);

  return { data, error, loading, refresh };
}

export type SseState = "connecting" | "open" | "closed";

/**
 * Subscribe to /live/results (SSE, event "inference_result"). The server
 * replays the last result per camera on connect. Returns the latest result per
 * camera id; the browser reconnects automatically on drop.
 */
export function useLiveResults(cameraId?: string) {
  const [results, setResults] = useState<Record<string, InferenceResult>>({});
  const [state, setState] = useState<SseState>("connecting");

  useEffect(() => {
    setResults({});
    setState("connecting");
    const url = `/live/results${cameraId ? `?camera_id=${encodeURIComponent(cameraId)}` : ""}`;
    const es = new EventSource(url);
    es.onopen = () => setState("open");
    es.onerror = () => setState(es.readyState === EventSource.CLOSED ? "closed" : "connecting");
    es.addEventListener("inference_result", (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as InferenceResult;
        if (!data.camera_id) return;
        setResults((prev) => {
          const cur = prev[data.camera_id];
          if (cur && typeof cur.seq === "number" && cur.seq >= data.seq) return prev;
          return { ...prev, [data.camera_id]: data };
        });
      } catch {
        /* ignore malformed frames */
      }
    });
    return () => es.close();
  }, [cameraId]);

  return { results, state };
}

/** Observe the rendered box size of an element. */
export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r) setSize({ width: r.width, height: r.height });
    });
    ro.observe(el);
    setSize({ width: el.clientWidth, height: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  return { ref, size };
}

/** Local toast-free notice with auto-clear. */
export function useNotice(ttlMs = 5000) {
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const timer = useRef<number | null>(null);
  const show = useCallback(
    (kind: "ok" | "error", text: string) => {
      setNotice({ kind, text });
      if (timer.current) window.clearTimeout(timer.current);
      if (kind === "ok") timer.current = window.setTimeout(() => setNotice(null), ttlMs);
    },
    [ttlMs]
  );
  const clear = useCallback(() => setNotice(null), []);
  return { notice, show, clear };
}
