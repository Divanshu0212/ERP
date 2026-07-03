"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Poll an async fetch on a fixed interval until a stop condition is met or a
 * timeout elapses. Used by the saga / escalation demos to watch a resource
 * transition (allocation pending -> confirmed, grievance unscored -> scored).
 *
 * The poll is started explicitly via `start()` rather than on mount so the demo
 * pages can kick it off after a user action (pay, submit).
 */

/** Status of a poll run. */
export type PollStatus = "idle" | "polling" | "done" | "timeout" | "error";

export interface UsePollOptions<T> {
  /** Fetches the current value of the resource. */
  fetcher: () => Promise<T>;
  /** Returns true when polling should stop (the awaited transition happened). */
  isDone: (value: T) => boolean;
  /** Delay between polls, in ms. */
  intervalMs: number;
  /** Give up after this many ms without `isDone` becoming true. */
  timeoutMs: number;
}

export interface UsePollResult<T> {
  status: PollStatus;
  data: T | null;
  error: string | null;
  /** Begin polling. Resets any prior run. */
  start: () => void;
  /** Stop polling and reset to idle. */
  reset: () => void;
}

export function usePoll<T>({
  fetcher,
  isDone,
  intervalMs,
  timeoutMs,
}: UsePollOptions<T>): UsePollResult<T> {
  const [status, setStatus] = useState<PollStatus>("idle");
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Timers and a generation counter so a stale in-flight fetch from a previous
  // run can't mutate state after the run was reset/superseded.
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const genRef = useRef(0);

  // Keep the latest callbacks without making them poll dependencies.
  const fetcherRef = useRef(fetcher);
  const isDoneRef = useRef(isDone);
  fetcherRef.current = fetcher;
  isDoneRef.current = isDone;

  const clearTimers = useCallback(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    genRef.current += 1;
    clearTimers();
    setStatus("idle");
    setData(null);
    setError(null);
  }, [clearTimers]);

  const start = useCallback(() => {
    genRef.current += 1;
    const gen = genRef.current;
    clearTimers();
    setStatus("polling");
    setData(null);
    setError(null);

    const tick = async () => {
      try {
        const value = await fetcherRef.current();
        if (gen !== genRef.current) return; // superseded
        setData(value);
        if (isDoneRef.current(value)) {
          clearTimers();
          setStatus("done");
        }
      } catch (e) {
        if (gen !== genRef.current) return;
        clearTimers();
        setError(e instanceof Error ? e.message : "Polling failed.");
        setStatus("error");
      }
    };

    // Fire once immediately, then on the interval.
    void tick();
    intervalRef.current = setInterval(() => void tick(), intervalMs);
    timeoutRef.current = setTimeout(() => {
      if (gen !== genRef.current) return;
      clearTimers();
      // Only a poll still in progress becomes a timeout.
      setStatus((s) => (s === "polling" ? "timeout" : s));
    }, timeoutMs);
  }, [clearTimers, intervalMs, timeoutMs]);

  // Clean up timers if the component unmounts mid-poll.
  useEffect(() => clearTimers, [clearTimers]);

  return { status, data, error, start, reset };
}
