import { describe, expect, it } from "vitest";
import { parseBannerZoomInput } from "./BannerCropModal";

describe("parseBannerZoomInput", () => {
  it("accepts plain zoom decimals and clamps to cropper bounds", () => {
    expect(parseBannerZoomInput("1.25", 1)).toBe(1.25);
    expect(parseBannerZoomInput(".5", 2)).toBe(1);
    expect(parseBannerZoomInput("4", 2)).toBe(3);
  });

  it("keeps the current zoom for ambiguous or malformed values", () => {
    for (const value of ["", "abc", "1e2", "0x2", "Infinity"]) {
      expect(parseBannerZoomInput(value, 1.75)).toBe(1.75);
    }
  });
});
