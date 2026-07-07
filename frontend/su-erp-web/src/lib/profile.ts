// Profile fetch/update helpers shared by every non-superadmin role's
// /profile page. Backed by auth-service's MyProfileView (Task 2):
// GET/PATCH /api/v1/auth/users/me/profile/. Superadmin has no UserProfile
// row and gets a 403 from the backend if these are ever called for it.

import { api } from "@/lib/api";

export interface UserProfile {
  phone: string;
  address: string;
  date_of_birth: string | null;
  gender: string;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  blood_group: string;
  profile_photo_url: string;
  updated_at: string;
}

export type UserProfileUpdate = Partial<Omit<UserProfile, "updated_at">>;

const PROFILE_PATH = "/api/v1/auth/users/me/profile/";

export async function getMyProfile(): Promise<UserProfile> {
  return api.get<UserProfile>(PROFILE_PATH);
}

export async function updateMyProfile(patch: UserProfileUpdate): Promise<UserProfile> {
  return api.patch<UserProfile>(PROFILE_PATH, patch);
}
