import { afterEach, describe, expect, it, vi } from "vitest";

import { uploadPayrollImport } from "../api/payrollImports";

describe("payroll import API transport", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("lets the browser provide the multipart boundary for FormData uploads", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "import-1" }), { status: 201, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File(["sample"], "bordro.png", { type: "image/png" });

    await uploadPayrollImport(file);

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });
});
