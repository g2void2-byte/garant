import { describe, expect, it } from "vitest";
import { safeMediaUrl } from "./mediaLinks";

describe("safeMediaUrl", () => {
  it("accepts relative media URLs and preserves signed query params", () => {
    expect(safeMediaUrl(" /media/deal/proof.png?exp=1&sig=abc ")).toBe(
      "/media/deal/proof.png?exp=1&sig=abc",
    );
  });

  it.each([
    "",
    "javascript:alert(1)",
    "data:image/svg+xml,<svg onload=alert(1)>",
    "https://evil.example/media/deal/proof.png",
    "//evil.example/media/deal/proof.png",
    "/admin/deals",
    "/media/../admin/deals",
  ])("rejects unsafe media URL %s", (url) => {
    expect(safeMediaUrl(url)).toBeNull();
  });
});
