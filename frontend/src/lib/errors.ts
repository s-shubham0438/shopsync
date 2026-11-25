import { ApiError } from "@/api/types";

const FIELD_HINTS: Record<string, string> = {
  email: "Please enter a valid email address.",
  full_name: "Please enter your name.",
  phone: "Please enter a valid 10-digit mobile number.",
  code: "Please enter the 6-digit code.",
  password: "Please check your password.",
  token: "This link is invalid or has expired.",
};

/** A short, user-facing sentence for any error thrown by the API layer. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      const minutes = err.retryAfter ? Math.ceil(err.retryAfter / 60) : null;
      return minutes
        ? `Too many attempts. Please try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`
        : "Too many attempts. Please try again later.";
    }
    if (err.code === "validation_error" && err.details?.length) {
      const detail = err.details[0]!;
      // Our own rules (e.g. weak passwords) carry friendly messages; framework ones don't.
      if (detail.type && !detail.type.includes(".") && detail.type.startsWith("weak_")) return detail.message;
      const field = detail.loc?.[detail.loc.length - 1];
      if (typeof field === "string" && FIELD_HINTS[field]) return FIELD_HINTS[field];
      return "Please check the highlighted details and try again.";
    }
    if (err.status >= 500 && err.code !== "service_unavailable" && err.code !== "coming_soon") {
      return "Something went wrong on our side. Please try again.";
    }
    return err.message;
  }
  if (err instanceof TypeError) return "Can't reach ShopSync. Check your connection and try again.";
  return "Something went wrong. Please try again.";
}
