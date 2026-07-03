"use client";

import type { ReactNode } from "react";

/**
 * A titled panel that renders one of loading / error / empty / content states.
 * Shared by the role dashboards so every data section looks and behaves alike.
 */
export function DataPanel({
  title,
  loading,
  error,
  isEmpty,
  emptyLabel = "Nothing to show.",
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
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-gray-950">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-50">{title}</h2>
        {action}
      </div>
      {loading ? (
        <p role="status" className="text-sm text-gray-500 dark:text-gray-400">
          Loading…
        </p>
      ) : error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : isEmpty ? (
        <p className="text-sm text-gray-500 dark:text-gray-400">{emptyLabel}</p>
      ) : (
        children
      )}
    </div>
  );
}
