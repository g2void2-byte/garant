import { describe, expect, it } from "vitest";

import {
  formatAdminAmount,
  formatAdminRating,
  formatAdminUsd,
  formatAdminUsdSuffix,
  formatAdminUsername,
} from "./format";

describe("admin format helpers", () => {
  it("formats Telegram handles and explicit missing-username labels", () => {
    expect(formatAdminUsername("alice")).toBe("@alice");
    expect(formatAdminUsername("  alice  ")).toBe("@alice");
    expect(formatAdminUsername(null)).toBe("username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d");
    expect(formatAdminUsername("")).toBe("username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d");
  });

  it("formats decimal-string admin money values without accepting ambiguous notation", () => {
    expect(formatAdminAmount("12.3456", 4)).toBe("12.3456");
    expect(formatAdminAmount("1e3", 4)).toBe("\u2014");
    expect(formatAdminUsd("1500.5")).toBe("$1500.50");
    expect(formatAdminUsdSuffix("1500.5")).toBe("1500.50 $");
    expect(formatAdminUsd("1e3")).toBe("\u2014");
    expect(formatAdminUsdSuffix("0x10")).toBe("\u2014");
  });

  it("formats string ratings and rejects malformed or out-of-range values", () => {
    expect(formatAdminRating("4.75")).toBe("4.8");
    expect(formatAdminRating("1e1")).toBe("\u2014");
    expect(formatAdminRating(6)).toBe("\u2014");
  });
});
