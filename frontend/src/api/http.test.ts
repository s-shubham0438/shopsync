import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { describeError } from "@/lib/errors";

import { httpApi } from "./http";
import { onSessionExpired } from "./session";
import { ApiError } from "./types";

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

const json = (status: number, body: unknown, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

const unauthorized = () => json(401, { error: { code: "unauthorized", message: "Authentication required." } });

let calls: { url: string; method: string; credentials?: RequestCredentials }[];

function serve(handler: Handler) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, method: init.method ?? "GET", credentials: init.credentials });
      return handler(url, init);
    }),
  );
}

const paths = () => calls.map((c) => `${c.method} ${c.url.replace(/^.*\/api\/v1/, "")}`);

beforeEach(() => {
  calls = [];
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("session handling", () => {
  it("sends cookies with every request", async () => {
    serve(() => json(200, []));
    await httpApi.getCategories();
    expect(calls[0]!.credentials).toBe("include");
  });

  it("refreshes once on 401 and retries the original request", async () => {
    let refreshed = false;
    serve((url) => {
      if (url.endsWith("/auth/refresh")) {
        refreshed = true;
        return new Response(null, { status: 204 });
      }
      return refreshed ? json(200, [{ id: "c1" }]) : unauthorized();
    });
    await expect(httpApi.getCategories()).resolves.toEqual([{ id: "c1" }]);
    expect(paths()).toEqual(["GET /categories", "POST /auth/refresh", "GET /categories"]);
  });

  it("shares one refresh between concurrent 401s", async () => {
    let refreshed = false;
    serve(async (url) => {
      if (url.endsWith("/auth/refresh")) {
        await new Promise((r) => setTimeout(r, 10));
        refreshed = true;
        return new Response(null, { status: 204 });
      }
      return refreshed ? json(200, []) : unauthorized();
    });
    await Promise.all([httpApi.getCategories(), httpApi.getPlatforms(), httpApi.deals()]);
    expect(paths().filter((p) => p === "POST /auth/refresh")).toHaveLength(1);
  });

  it("signals an expired session when the refresh is refused, without looping", async () => {
    serve(() => unauthorized());
    const expired = vi.fn();
    const stop = onSessionExpired(expired);
    await expect(httpApi.getCategories()).rejects.toMatchObject({ status: 401 });
    stop();
    expect(expired).toHaveBeenCalledOnce();
    expect(paths()).toEqual(["GET /categories", "POST /auth/refresh"]);
  });

  it("never refreshes for auth endpoints themselves", async () => {
    serve(() => json(401, { error: { code: "invalid_credentials", message: "Incorrect email or password." } }));
    await expect(httpApi.auth.login("a@example.com", "x")).rejects.toMatchObject({ code: "invalid_credentials" });
    expect(paths()).toEqual(["POST /auth/login"]);
  });

  it("me() resolves to null when signed out", async () => {
    serve(() => unauthorized());
    await expect(httpApi.auth.me()).resolves.toBeNull();
    expect(paths()).toEqual(["GET /auth/me", "POST /auth/refresh"]);
  });

  it("me() restores the session through a refresh", async () => {
    let refreshed = false;
    serve((url) => {
      if (url.endsWith("/auth/refresh")) {
        refreshed = true;
        return new Response(null, { status: 204 });
      }
      return refreshed ? json(200, { id: "u1" }) : unauthorized();
    });
    await expect(httpApi.auth.me()).resolves.toEqual({ id: "u1" });
  });
});

describe("errors", () => {
  it("keeps code, details, request id and Retry-After", async () => {
    serve(() =>
      json(
        429,
        { error: { code: "rate_limited", message: "Too many requests.", request_id: "r-1" } },
        { "Retry-After": "120" },
      ),
    );
    const err = await httpApi.auth.login("a@example.com", "x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 429, code: "rate_limited", requestId: "r-1", retryAfter: 120 });
    expect(describeError(err)).toBe("Too many attempts. Please try again in 2 minutes.");
  });

  it("handles non-JSON error bodies", async () => {
    serve(() => new Response("<html>Bad gateway</html>", { status: 502, statusText: "Bad Gateway" }));
    const err = await httpApi.getCategories().catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 502, code: "http_error" });
    expect(describeError(err)).toBe("Something went wrong on our side. Please try again.");
  });
});

describe("describeError", () => {
  const validation = (type: string, loc: (string | number)[], message: string) =>
    new ApiError(422, { code: "validation_error", message: "Request validation failed.", details: [{ loc, message, type }] });

  it("shows our own friendly validation messages", () => {
    expect(describeError(validation("weak_password", ["body", "password"], "This password is too common."))).toBe(
      "This password is too common.",
    );
  });

  it("replaces framework messages with field hints", () => {
    expect(describeError(validation("value_error", ["body", "email"], "value is not a valid email address: ..."))).toBe(
      "Please enter a valid email address.",
    );
  });

  it("passes through server messages such as the duplicate-email notice", () => {
    const taken = new ApiError(409, {
      code: "email_taken",
      message: "An account with this email already exists. Please log in.",
    });
    expect(describeError(taken)).toBe("An account with this email already exists. Please log in.");
  });

  it("explains network failures", () => {
    expect(describeError(new TypeError("Failed to fetch"))).toBe("Can't reach ShopSync. Check your connection and try again.");
  });
});
