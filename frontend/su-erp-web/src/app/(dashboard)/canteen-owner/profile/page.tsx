"use client";

import { DashboardShell } from "@/components/DashboardShell";
import { ProfileForm } from "@/components/ProfileForm";

export default function CanteenOwnerProfilePage() {
  return (
    <DashboardShell title="Profile" role="canteen_owner">
      <ProfileForm />
    </DashboardShell>
  );
}
