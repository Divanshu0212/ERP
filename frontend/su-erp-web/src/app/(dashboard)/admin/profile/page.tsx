"use client";

import { DashboardShell } from "@/components/DashboardShell";
import { ProfileForm } from "@/components/ProfileForm";

export default function AdminProfilePage() {
  return (
    <DashboardShell title="Profile" role="admin">
      <ProfileForm />
    </DashboardShell>
  );
}
