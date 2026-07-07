// Unit tests for the label-safe initials helper introduced for the avatar fix:
// `sub` (and thus the avatar label) is now frequently a user_code, not an
// email, so `initialsFromLabel` must handle both shapes gracefully.
import { describe, it, expect } from "vitest";

import { initialsFromLabel } from "./tenant-color";

describe("initialsFromLabel", () => {
  it("delegates to email-style initials when the label contains '@'", () => {
    expect(initialsFromLabel("jane.doe@acme.edu")).toBe("JD");
  });

  it("takes the first two characters, uppercased, for a plain user_code", () => {
    expect(initialsFromLabel("stu-0042")).toBe("ST");
  });

  it("falls back to '?' for an empty label", () => {
    expect(initialsFromLabel("")).toBe("?");
  });

  it("trims whitespace before taking initials", () => {
    expect(initialsFromLabel("  wd7  ")).toBe("WD");
  });
});
