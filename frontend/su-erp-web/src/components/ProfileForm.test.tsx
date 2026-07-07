// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const getMyProfile = vi.fn();
const updateMyProfile = vi.fn();
vi.mock("@/lib/profile", () => ({
  getMyProfile: (...args: unknown[]) => getMyProfile(...args),
  updateMyProfile: (...args: unknown[]) => updateMyProfile(...args),
}));

import { ProfileForm } from "@/components/ProfileForm";

function baseProfile(overrides: Record<string, unknown> = {}) {
  return {
    phone: "1234567890",
    address: "",
    date_of_birth: null,
    gender: "",
    emergency_contact_name: "",
    emergency_contact_phone: "",
    blood_group: "",
    profile_photo_url: "",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ProfileForm", () => {
  beforeEach(() => {
    getMyProfile.mockReset();
    updateMyProfile.mockReset();
    getMyProfile.mockResolvedValue(baseProfile());
  });

  it("loads and displays the existing phone number", async () => {
    render(<ProfileForm />);

    await waitFor(() => {
      expect(screen.getByLabelText("Phone")).toHaveValue("1234567890");
    });
  });

  it("saves an edited field", async () => {
    updateMyProfile.mockResolvedValue(
      baseProfile({ phone: "9999999999", updated_at: "2026-01-02T00:00:00Z" }),
    );
    const user = userEvent.setup();
    render(<ProfileForm />);
    await waitFor(() => expect(screen.getByLabelText("Phone")).toHaveValue("1234567890"));

    await user.clear(screen.getByLabelText("Phone"));
    await user.type(screen.getByLabelText("Phone"), "9999999999");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => {
      expect(updateMyProfile).toHaveBeenCalledWith(
        expect.objectContaining({ phone: "9999999999" }),
      );
    });
    expect(await screen.findByText("Profile saved.")).toBeInTheDocument();
  });

  it("shows an error message when loading fails", async () => {
    getMyProfile.mockReset();
    getMyProfile.mockRejectedValue(new Error("Network error"));

    render(<ProfileForm />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Network error");
  });
});
