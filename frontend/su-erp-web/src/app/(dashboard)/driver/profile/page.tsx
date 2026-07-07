"use client";

import { DashboardShell } from "@/components/DashboardShell";
import { ProfileForm } from "@/components/ProfileForm";

export default function DriverProfilePage() {
  return (
    <DashboardShell title="Profile" role="driver">
      <ProfileForm />
    </DashboardShell>
  );
}
