"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { DataPanel } from "@/components/DataPanel";
import { api, ApiError } from "@/lib/api";
import { listItems } from "@/lib/paginate";

interface Allocation {
  id: string;
  student_id: string;
  room: string;
  status: string;
}

interface Grievance {
  id: string;
  raised_by: string;
  status: string;
  assigned_to: string;
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

function WardenContent() {
  const [allocations, setAllocations] = useState<Allocation[]>([]);
  const [allocLoading, setAllocLoading] = useState(true);
  const [allocError, setAllocError] = useState<string | null>(null);

  const [grievances, setGrievances] = useState<Grievance[]>([]);
  const [grievLoading, setGrievLoading] = useState(true);
  const [grievError, setGrievError] = useState<string | null>(null);

  const loadAllocations = useCallback(async () => {
    setAllocLoading(true);
    setAllocError(null);
    try {
      const data = await api.get("/api/v1/hostel/allocations?status=pending");
      setAllocations(listItems<Allocation>(data));
    } catch (e) {
      setAllocError(errMsg(e));
    } finally {
      setAllocLoading(false);
    }
  }, []);

  const loadGrievances = useCallback(async () => {
    setGrievLoading(true);
    setGrievError(null);
    try {
      const data = await api.get("/api/v1/grievance?status=escalated");
      setGrievances(listItems<Grievance>(data));
    } catch (e) {
      setGrievError(errMsg(e));
    } finally {
      setGrievLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAllocations();
    void loadGrievances();
  }, [loadAllocations, loadGrievances]);

  return (
    <>
      <DataPanel
        title="Pending Hostel Allocations"
        loading={allocLoading}
        error={allocError}
        isEmpty={allocations.length === 0}
        emptyLabel="No pending allocations."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-gray-500 dark:border-gray-800 dark:text-gray-400">
                <th className="py-2 pr-4 font-medium">Student</th>
                <th className="py-2 pr-4 font-medium">Room</th>
                <th className="py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {allocations.map((a) => (
                <tr
                  key={a.id}
                  className="border-b border-gray-100 last:border-0 dark:border-gray-900"
                >
                  <td className="py-2 pr-4">{a.student_id}</td>
                  <td className="py-2 pr-4">{a.room}</td>
                  <td className="py-2 capitalize">{a.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DataPanel>

      <DataPanel
        title="Escalated Grievances"
        loading={grievLoading}
        error={grievError}
        isEmpty={grievances.length === 0}
        emptyLabel="No escalated grievances."
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-gray-500 dark:border-gray-800 dark:text-gray-400">
                <th className="py-2 pr-4 font-medium">Ticket</th>
                <th className="py-2 pr-4 font-medium">Raised by</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 font-medium">Assigned to</th>
              </tr>
            </thead>
            <tbody>
              {grievances.map((g) => (
                <tr
                  key={g.id}
                  className="border-b border-gray-100 last:border-0 dark:border-gray-900"
                >
                  <td className="py-2 pr-4 font-mono text-xs">{g.id}</td>
                  <td className="py-2 pr-4">{g.raised_by}</td>
                  <td className="py-2 pr-4 capitalize">{g.status}</td>
                  <td className="py-2">{g.assigned_to}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </DataPanel>
    </>
  );
}

export default function WardenDashboard() {
  return (
    <DashboardShell title="Warden Dashboard" role="warden">
      <WardenContent />
    </DashboardShell>
  );
}
