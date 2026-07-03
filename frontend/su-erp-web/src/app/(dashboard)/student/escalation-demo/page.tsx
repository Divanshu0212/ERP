"use client";

import { useCallback, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { api, ApiError } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";

// ML escalation demo: grievance scoring.
//
// A student submits a grievance with urgent text; the ai-service scores it
// (sentiment + urgency) and emits `grievance.scored`, which updates the
// ticket. This page submits the ticket, then polls it until the urgency /
// sentiment fields appear (1s interval, 5s timeout).

const PREFILLED_TEXT = "the warden is threatening me, this is ragging";

interface Grievance {
  id: string;
  description: string;
  status: string;
  urgency: string | null;
  sentiment_score: number | null;
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function isScored(g: Grievance): boolean {
  return g.urgency != null || g.sentiment_score != null;
}

function urgencyClass(urgency: string): string {
  switch ((urgency || "").toLowerCase()) {
    case "critical":
    case "high":
      return "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300";
    case "medium":
      return "bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300";
    default:
      return "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";
  }
}

function sentimentLabel(score: number): string {
  if (score < -0.2) return "negative";
  if (score > 0.2) return "positive";
  return "neutral";
}

function EscalationDemoContent() {
  const [text, setText] = useState(PREFILLED_TEXT);
  const [ticketId, setTicketId] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const poll = usePoll<Grievance>({
    fetcher: async () => api.get<Grievance>(`/api/v1/grievance/${ticketId}`),
    isDone: isScored,
    intervalMs: 1000,
    timeoutMs: 5000,
  });

  const submit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setSubmitError(null);
      setSubmitting(true);
      try {
        const created = await api.post<Grievance>("/api/v1/grievance", {
          description: text,
        });
        setTicketId(created.id);
        poll.start();
      } catch (err) {
        setSubmitError(errMsg(err));
      } finally {
        setSubmitting(false);
      }
    },
    [text, poll],
  );

  const scored = poll.data && isScored(poll.data) ? poll.data : null;

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-600 shadow-sm dark:border-gray-800 dark:bg-gray-950 dark:text-gray-400">
        Submit a grievance and watch the ML pipeline score it. The ai-service
        classifies sentiment and urgency, then emits{" "}
        <code className="rounded bg-gray-100 px-1 py-0.5 text-xs dark:bg-gray-800">
          grievance.scored
        </code>{" "}
        — the ticket updates and this page reflects it.
      </div>

      <form
        onSubmit={submit}
        className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-950"
      >
        <label
          htmlFor="grievance-text"
          className="block text-sm font-medium text-gray-900 dark:text-gray-50"
        >
          Grievance description
        </label>
        <textarea
          id="grievance-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          className="mt-2 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
        />
        <button
          type="submit"
          disabled={submitting || poll.status === "polling" || text.trim().length === 0}
          className="mt-3 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500 dark:disabled:bg-gray-800 dark:disabled:text-gray-500"
        >
          {submitting ? "Submitting…" : "Submit Grievance"}
        </button>
        {submitError && (
          <p role="alert" className="mt-2 text-sm text-red-600 dark:text-red-400">
            {submitError}
          </p>
        )}
      </form>

      {ticketId && (
        <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-950">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-900 dark:text-gray-50">
              ML Scoring
            </h2>
            <span className="font-mono text-xs text-gray-400">{ticketId}</span>
          </div>

          {poll.status === "polling" && (
            <p role="status" className="mt-3 text-sm text-gray-500 dark:text-gray-400">
              Waiting for the AI service to score this ticket…
            </p>
          )}
          {poll.status === "timeout" && (
            <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
              Timed out waiting for scoring. The ai-service may be busy.
            </p>
          )}
          {poll.status === "error" && (
            <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
              {poll.error ?? "Scoring failed."}
            </p>
          )}

          {scored && (
            <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Urgency
                </dt>
                <dd className="mt-1">
                  {scored.urgency != null ? (
                    <span
                      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${urgencyClass(scored.urgency)}`}
                    >
                      {scored.urgency}
                    </span>
                  ) : (
                    <span className="text-sm text-gray-400">—</span>
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  Sentiment
                </dt>
                <dd className="mt-1 text-sm text-gray-900 dark:text-gray-100">
                  {scored.sentiment_score != null ? (
                    <>
                      <span className="capitalize">
                        {sentimentLabel(scored.sentiment_score)}
                      </span>{" "}
                      <span className="tabular-nums text-gray-500 dark:text-gray-400">
                        ({scored.sentiment_score.toFixed(2)})
                      </span>
                    </>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </dd>
              </div>
            </dl>
          )}
        </div>
      )}
    </div>
  );
}

export default function EscalationDemoPage() {
  return (
    <DashboardShell title="Escalation Demo · Grievance Scoring" role="student">
      <EscalationDemoContent />
    </DashboardShell>
  );
}
