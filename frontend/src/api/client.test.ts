import { afterEach, expect, it, vi } from "vitest";

import { apiRequest } from "./client";

afterEach(() => vi.unstubAllGlobals());

it("keeps JSON content type when a request adds an idempotency header", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ id: "brief-1" }), {
      status: 201,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  const body = JSON.stringify({ scenario: "虚构的运营场景" });
  await apiRequest<{ id: string }>("/briefs/parse", {
    method: "POST",
    headers: { "Idempotency-Key": "parse-test-1" },
    body,
  });

  expect(fetchMock).toHaveBeenCalledOnce();
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/api/v1/briefs/parse");
  expect(init.credentials).toBe("include");
  expect(init.body).toBe(body);
  const headers = new Headers(init.headers);
  expect(headers.get("Content-Type")).toBe("application/json");
  expect(headers.get("Idempotency-Key")).toBe("parse-test-1");
});
