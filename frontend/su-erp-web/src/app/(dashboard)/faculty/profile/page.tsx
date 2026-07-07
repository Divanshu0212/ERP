"use client";

import { DashboardShell } from "@/components/DashboardShell";
import { ProfileForm } from "@/components/ProfileForm";

export default function FacultyProfilePage() {
  return (
    <DashboardShell title="Profile" role="faculty">
      <ProfileForm />
    </DashboardShell>
  );
}
