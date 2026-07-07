"use client";

import { DashboardShell } from "@/components/DashboardShell";
import { ProfileForm } from "@/components/ProfileForm";

export default function StudentProfilePage() {
  return (
    <DashboardShell title="Profile" role="student">
      <ProfileForm />
    </DashboardShell>
  );
}
