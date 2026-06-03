import { describe, expect, it } from "vitest";

import { formatAdminUsername } from "./format";

describe("admin format helpers", () => {
  it("formats Telegram handles and explicit missing-username labels", () => {
    expect(formatAdminUsername("alice")).toBe("@alice");
    expect(formatAdminUsername("  alice  ")).toBe("@alice");
    expect(formatAdminUsername(null)).toBe("username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d");
    expect(formatAdminUsername("")).toBe("username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d");
  });
});
