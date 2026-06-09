import { describe, expect, it } from "vitest";
import {
  isPositiveSafeInteger,
  parsePositiveIntRouteParam,
  parsePositiveIntValue,
} from "./routeParams";

describe("route param integer parsing", () => {
  it("accepts canonical positive decimal ids", () => {
    expect(parsePositiveIntRouteParam("1")).toBe(1);
    expect(parsePositiveIntRouteParam("42")).toBe(42);
    expect(parsePositiveIntValue(42)).toBe(42);
  });

  it("rejects ambiguous or unsafe route ids", () => {
    for (const value of [
      undefined,
      "",
      "0",
      "01",
      "1.5",
      "1e2",
      "0x2",
      " 5",
      String(Number.MAX_SAFE_INTEGER + 1),
    ]) {
      expect(parsePositiveIntRouteParam(value)).toBeUndefined();
    }
  });

  it("rejects non-integer numeric values", () => {
    expect(isPositiveSafeInteger(1)).toBe(true);
    expect(parsePositiveIntValue(0)).toBeUndefined();
    expect(parsePositiveIntValue(1.5)).toBeUndefined();
    expect(parsePositiveIntValue(Number.POSITIVE_INFINITY)).toBeUndefined();
  });
});
