// Unit tests for fetchMe: the caller's own identity record, used to render
// the avatar/profile with the real email instead of the JWT `sub` claim
// (which is a user_code, not an email, as of the user_code migration).
import { describe, it, expect, afterEach, vi } from "vitest";

import { fetchMe } from "@/lib/session";

describe("fetchMe", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("fetches /api/v1/auth/me and returns the unwrapped envelope data", async () => {
    const meData = {
      user_code: "stu-0042",
      email: "jane.doe@acme.edu",
      role: "student",
      tenant: "acme",
    };
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ success: true, data: meData, message: "", errors: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchMe();

    expect(result).toEqual(meData);
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/me");
  });
});
