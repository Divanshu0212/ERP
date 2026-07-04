"use client";

import { useEffect, useRef } from "react";

/**
 * Re-run `callback` on a fixed interval while the tab is visible, pausing when
 * it's backgrounded (Page Visibility API) and firing once immediately on
 * regaining focus so state isn't stale after a tab switch.
 *
 * Used for near-real-time status views (e.g. canteen order tracking) where a
 * websocket/SSE push channel doesn't exist — short-interval polling is the
 * standard fallback for this kind of "did it change yet" list refresh.
 */
export function usePolling(callback: () => void, intervalMs: number, enabled = true) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!enabled) return;

    let id: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (id !== null) return;
      id = setInterval(() => callbackRef.current(), intervalMs);
    };
    const stop = () => {
      if (id !== null) {
        clearInterval(id);
        id = null;
      }
    };
    const handleVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        callbackRef.current();
        start();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    if (!document.hidden) start();

    return () => {
      stop();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [intervalMs, enabled]);
}
