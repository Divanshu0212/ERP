"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { getMyProfile, updateMyProfile } from "@/lib/profile";
import type { UserProfile } from "@/lib/profile";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";

const EMPTY: UserProfile = {
  phone: "",
  address: "",
  date_of_birth: null,
  gender: "",
  emergency_contact_name: "",
  emergency_contact_phone: "",
  blood_group: "",
  profile_photo_url: "",
  updated_at: "",
};

/** Self-fetching profile editor shared by every role's /profile page. */
export function ProfileForm() {
  const [profile, setProfile] = useState<UserProfile>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMyProfile()
      .then((data) => {
        if (!cancelled) setProfile(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load profile.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function set<K extends keyof UserProfile>(key: K, value: UserProfile[K]) {
    setProfile((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const updated = await updateMyProfile({
        phone: profile.phone,
        address: profile.address,
        date_of_birth: profile.date_of_birth,
        gender: profile.gender,
        emergency_contact_name: profile.emergency_contact_name,
        emergency_contact_phone: profile.emergency_contact_phone,
        blood_group: profile.blood_group,
        profile_photo_url: profile.profile_photo_url,
      });
      setProfile(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-muted">Loading…</p>;
  }

  return (
    <Card>
      <CardHeader title="Profile details" />
      <CardBody>
        <form onSubmit={handleSubmit} className="space-y-4">
          <Field label="Phone" htmlFor="phone">
            <Input id="phone" value={profile.phone} onChange={(e) => set("phone", e.target.value)} />
          </Field>
          <Field label="Address" htmlFor="address">
            <Input
              id="address"
              value={profile.address}
              onChange={(e) => set("address", e.target.value)}
            />
          </Field>
          <Field label="Date of birth" htmlFor="date_of_birth">
            <Input
              id="date_of_birth"
              type="date"
              value={profile.date_of_birth ?? ""}
              onChange={(e) => set("date_of_birth", e.target.value || null)}
            />
          </Field>
          <Field label="Gender" htmlFor="gender">
            <Input id="gender" value={profile.gender} onChange={(e) => set("gender", e.target.value)} />
          </Field>
          <Field label="Blood group" htmlFor="blood_group">
            <Input
              id="blood_group"
              value={profile.blood_group}
              onChange={(e) => set("blood_group", e.target.value)}
            />
          </Field>
          <Field label="Emergency contact name" htmlFor="emergency_contact_name">
            <Input
              id="emergency_contact_name"
              value={profile.emergency_contact_name}
              onChange={(e) => set("emergency_contact_name", e.target.value)}
            />
          </Field>
          <Field label="Emergency contact phone" htmlFor="emergency_contact_phone">
            <Input
              id="emergency_contact_phone"
              value={profile.emergency_contact_phone}
              onChange={(e) => set("emergency_contact_phone", e.target.value)}
            />
          </Field>
          <Field label="Profile photo URL" htmlFor="profile_photo_url">
            <Input
              id="profile_photo_url"
              value={profile.profile_photo_url}
              onChange={(e) => set("profile_photo_url", e.target.value)}
            />
          </Field>

          {error && <Alert tone="error">{error}</Alert>}
          {saved && <Alert tone="success">Profile saved.</Alert>}

          <Button type="submit" loading={saving}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
