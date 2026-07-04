"use client";

import type { ReactNode } from "react";

import { Card, CardHeader } from "@/components/ui/Card";

/**
 * A titled panel that renders one of loading / error / empty / content states.
 * Shared by the role dashboards so every data section looks and behaves alike.
 */
export function DataPanel({
  title,
  loading,
  error,
  isEmpty,
  emptyLabel = "Nothing to show yet.",
  action,
  children,
}: {
  title: string;
  loading: boolean;
  error: string | null;
  isEmpty?: boolean;
  emptyLabel?: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader title={title} action={action} />
      <div className="p-4">
        {loading ? (
          <p role="status" className="text-[13px] text-muted">
            Loading…
          </p>
        ) : error ? (
          <p role="alert" className="text-[13px] text-danger">
            {error}
          </p>
        ) : isEmpty ? (
          <p className="text-[13px] text-muted">{emptyLabel}</p>
        ) : (
          children
        )}
      </div>
    </Card>
  );
}
