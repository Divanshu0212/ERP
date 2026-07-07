// Unit tests for getMyProfile/updateMyProfile: the shared fetch/update helpers
// backing every role's /profile page (GET/PATCH /api/v1/auth/users/me/profile/).
import { describe, it, expect, vi, beforeEach } from "vitest";

const get = vi.fn();
const patch = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: { ...actual.api, get: (...args: unknown[]) => get(...args), patch: (...args: unknown[]) => patch(...args) },
  };
});

import { getMyProfile, updateMyProfile } from "@/lib/profile";

describe("profile lib", () => {
  beforeEach(() => {
    get.mockReset();
    patch.mockReset();
  });

  it("fetches the caller's profile", async () => {
    get.mockResolvedValue({
      phone: "123",
      address: "",
      date_of_birth: null,
      gender: "",
      emergency_contact_name: "",
      emergency_contact_phone: "",
      blood_group: "",
      profile_photo_url: "",
      updated_at: "2026-01-01T00:00:00Z",
    });

    const profile = await getMyProfile();

    expect(get).toHaveBeenCalledWith("/api/v1/auth/users/me/profile/");
    expect(profile.phone).toBe("123");
  });

  it("patches the caller's profile", async () => {
    patch.mockResolvedValue({ phone: "999" });

    await updateMyProfile({ phone: "999" });

    expect(patch).toHaveBeenCalledWith("/api/v1/auth/users/me/profile/", { phone: "999" });
  });
});
