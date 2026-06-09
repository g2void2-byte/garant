import { describe, expect, it } from "vitest";
import { safeMediaUrl, safeUserImageUrl } from "./mediaLinks";

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
    "/media/%2e%2e/admin/deals",
    "/media/deal//proof.png",
    "/media/deal/%2F/proof.png",
    "/media/deal\\proof.png",
    "/media/deal/proof.png#fragment",
    "/media/deal/proof .png",
  ])("rejects unsafe media URL %s", (url) => {
    expect(safeMediaUrl(url)).toBeNull();
  });

  it("accepts backend-contract user image URLs", () => {
    expect(safeUserImageUrl(" https://cdn.example/avatar.png?size=2 ")).toBe(
      "https://cdn.example/avatar.png?size=2",
    );
    expect(safeUserImageUrl("/media/avatar/user.png?exp=1&sig=abc")).toBe(
      "/media/avatar/user.png?exp=1&sig=abc",
    );
  });

  it.each([
    "",
    "http://cdn.example/avatar.png",
    "data:image/svg+xml,<svg onload=alert(1)>",
    "javascript:alert(1)",
    "https:///avatar.png",
    "https://cdn.example@evil.example/avatar.png",
    "https://user:pass@cdn.example/avatar.png",
    "https://cdn.example/avatar\\next.png",
    "https://cdn.example/avatar next.png",
    "/media/avatar//user.png",
    "/media/avatar/%2e%2e/user.png",
  ])("rejects unsafe user image URL %s", (url) => {
    expect(safeUserImageUrl(url)).toBeNull();
  });
});
