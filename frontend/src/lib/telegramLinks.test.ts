import { describe, expect, it } from "vitest";
import { buildTelegramUserUrl } from "./telegramLinks";

describe("buildTelegramUserUrl", () => {
  it("normalizes plain and @-prefixed usernames", () => {
    expect(buildTelegramUserUrl(" admin_1 ")).toBe("https://t.me/admin_1");
    expect(buildTelegramUserUrl("@admin_1")).toBe("https://t.me/admin_1");
  });

  it("adds message text as a query parameter without accepting raw query injection", () => {
    const url = buildTelegramUserUrl("admin_1", { text: "hello ?x=1" });
    expect(url).not.toBeNull();
    const parsed = new URL(url as string);
    expect(parsed.hostname).toBe("t.me");
    expect(parsed.pathname).toBe("/admin_1");
    expect(parsed.searchParams.get("text")).toBe("hello ?x=1");
  });

  it.each(["", "   ", "admin/name", "admin?text=x", "https://evil.test", "admin#x"])(
    "rejects unsafe username %s",
    (username) => {
      expect(buildTelegramUserUrl(username)).toBeNull();
    },
  );
});
