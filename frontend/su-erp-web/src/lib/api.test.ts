// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

import { api, ApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";

describe("api.upload", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setToken("tok");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts a file as multipart/form-data and unwraps the envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => ({ success: true, data: { batch_id: "b1" }, message: "ok", errors: null }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["a,b\n1,2"], "import.csv", { type: "text/csv" });
    const result = await api.upload<{ batch_id: string }>("/api/v1/hostel/allocate/bulk", file);

    expect(result).toEqual({ batch_id: "b1" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/hostel/allocate/bulk");
    expect(init.method).toBe("POST");
    expect(init.headers["Authorization"]).toBe("Bearer tok");
    expect(init.headers["Content-Type"]).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("throws ApiError when the envelope reports failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => ({ success: false, data: null, message: "Bad file.", errors: null }),
      status: 400,
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["x"], "import.csv");
    await expect(api.upload("/api/v1/hostel/allocate/bulk", file)).rejects.toThrow(ApiError);
  });
});
