import { describe, expect, it } from "vitest";
import {
  parseNonNegativeDecimalInput,
  parseNonNegativeIntInput,
  parsePositiveDecimalInput,
  parseSignedDecimalInput,
  parseSignedNonZeroDecimalInput,
} from "./formNumbers";

describe("form number parsing", () => {
  it("accepts plain decimal inputs", () => {
    expect(parsePositiveDecimalInput("1.25")).toBe(1.25);
    expect(parsePositiveDecimalInput(".5")).toBe(0.5);
    expect(parseSignedDecimalInput("-1.5")).toBe(-1.5);
    expect(parseSignedDecimalInput("0")).toBe(0);
    expect(parseSignedNonZeroDecimalInput("-25.5")).toBe(-25.5);
    expect(parseNonNegativeDecimalInput("0")).toBe(0);
    expect(parseNonNegativeIntInput("8", 8)).toBe(8);
  });

  it("rejects exponent, hex, non-finite and unsafe values", () => {
    for (const value of ["", "abc", "1e2", "0x10", "Infinity", "NaN"]) {
      expect(parsePositiveDecimalInput(value)).toBeNull();
      expect(parseSignedDecimalInput(value)).toBeNull();
      expect(parseSignedNonZeroDecimalInput(value)).toBeNull();
    }
    expect(parsePositiveDecimalInput("0")).toBeNull();
    expect(parseSignedNonZeroDecimalInput("0")).toBeNull();
    expect(parseNonNegativeIntInput("9", 8)).toBeNull();
    expect(parseNonNegativeIntInput(String(Number.MAX_SAFE_INTEGER + 1))).toBeNull();
  });
});
