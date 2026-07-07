"use client";

import { DashboardShell } from "@/components/DashboardShell";
import { ProfileForm } from "@/components/ProfileForm";

export default function WardenProfilePage() {
  return (
    <DashboardShell title="Profile" role="warden">
      <ProfileForm />
    </DashboardShell>
  );
}
