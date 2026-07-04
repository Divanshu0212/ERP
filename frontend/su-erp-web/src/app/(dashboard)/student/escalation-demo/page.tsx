"use client";

import { useCallback, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { api, ApiError } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/ui/StatusPill";

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
      <Card>
        <CardBody className="text-[13px] text-muted">
          Submit a grievance and watch the ML pipeline score it. The ai-service
          classifies sentiment and urgency, then emits{" "}
          <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[12px] text-ink">
            grievance.scored
          </code>{" "}
          — the ticket updates and this page reflects it.
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <form onSubmit={submit}>
            <label htmlFor="grievance-text" className="block text-[13px] font-medium text-ink">
              Grievance description
            </label>
            <textarea
              id="grievance-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              className="mt-2 w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink shadow-subtle focus:border-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
            />
            <Button
              type="submit"
              className="mt-3"
              loading={submitting || poll.status === "polling"}
              disabled={submitting || poll.status === "polling" || text.trim().length === 0}
            >
              {submitting ? "Submitting…" : "Submit Grievance"}
            </Button>
            {submitError && (
              <p role="alert" className="mt-2 text-[13px] text-danger">
                {submitError}
              </p>
            )}
          </form>
        </CardBody>
      </Card>

      {ticketId && (
        <Card>
          <CardHeader
            title="ML scoring"
            action={<span className="font-mono text-[12px] text-muted">{ticketId}</span>}
          />
          <CardBody>
            {poll.status === "polling" && (
              <p role="status" className="text-[13px] text-muted">
                Waiting for the AI service to score this ticket…
              </p>
            )}
            {poll.status === "timeout" && (
              <p role="alert" className="text-[13px] text-danger">
                Timed out waiting for scoring. The ai-service may be busy.
              </p>
            )}
            {poll.status === "error" && (
              <p role="alert" className="text-[13px] text-danger">
                {poll.error ?? "Scoring failed."}
              </p>
            )}

            {scored && (
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <dt className="text-eyebrow font-semibold uppercase text-muted">Urgency</dt>
                  <dd className="mt-1.5">
                    {scored.urgency != null ? (
                      <StatusPill status={scored.urgency} />
                    ) : (
                      <span className="text-sm text-muted">—</span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-eyebrow font-semibold uppercase text-muted">Sentiment</dt>
                  <dd className="mt-1.5 text-sm text-ink">
                    {scored.sentiment_score != null ? (
                      <>
                        <span className="capitalize">
                          {sentimentLabel(scored.sentiment_score)}
                        </span>{" "}
                        <span className="tabular-nums text-muted">
                          ({scored.sentiment_score.toFixed(2)})
                        </span>
                      </>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </dd>
                </div>
              </dl>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}

export default function EscalationDemoPage() {
  return (
    <DashboardShell title="Raise grievance" role="student">
      <EscalationDemoContent />
    </DashboardShell>
  );
}
