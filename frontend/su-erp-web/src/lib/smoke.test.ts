// Smoke test: both libs import and their core surface behaves.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import { apiCall, ApiError, api } from "@/lib/api";
import { getToken, setToken, clearToken, decodeToken } from "@/lib/auth";

// Minimal in-memory localStorage so auth helpers work under the node env.
function installLocalStorage() {
  const store = new Map<string, string>();
  const mock = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  };
  vi.stubGlobal("window", { localStorage: mock });
}

describe("auth lib", () => {
  beforeEach(() => installLocalStorage());
  afterEach(() => vi.unstubAllGlobals());

  it("round-trips the access token", () => {
    expect(getToken()).toBeNull();
    setToken("abc.def.ghi");
    expect(getToken()).toBe("abc.def.ghi");
    clearToken();
    expect(getToken()).toBeNull();
  });

  it("decodes JWT claims without verification", () => {
    // header.{ "sub":"u1","role":"student","tenant":"acme" }.sig
    const payload = Buffer.from(
      JSON.stringify({ sub: "u1", role: "student", tenant: "acme" }),
    ).toString("base64url");
    const token = `h.${payload}.s`;
    const claims = decodeToken(token);
    expect(claims.sub).toBe("u1");
    expect(claims.role).toBe("student");
    expect(claims.tenant).toBe("acme");
  });

  it("throws on a malformed token", () => {
    expect(() => decodeToken("not-a-jwt")).toThrow(/Malformed JWT/);
  });
});

describe("api lib", () => {
  beforeEach(() => installLocalStorage());
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("unwraps a successful envelope and returns data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ success: true, data: { id: 7 }, message: "ok", errors: null }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    const data = await apiCall<{ id: number }>("GET", "/api/v1/thing");
    expect(data.id).toBe(7);
  });

  it("throws ApiError with the envelope message on success:false", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ success: false, data: null, message: "nope", errors: ["bad"] }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );
    await expect(api.get("/api/v1/thing")).rejects.toMatchObject({
      name: "ApiError",
      message: "nope",
      status: 400,
    });
  });

  it("throws ApiError on network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("boom");
      }),
    );
    await expect(apiCall("GET", "/api/v1/thing")).rejects.toBeInstanceOf(ApiError);
  });

  it("attaches the bearer token when present", async () => {
    setToken("tok-123");
    const fetchMock = vi.fn(async () =>
      new Response(
        JSON.stringify({ success: true, data: null, message: "", errors: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiCall("GET", "/api/v1/thing");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["Authorization"]).toBe("Bearer tok-123");
  });
});
