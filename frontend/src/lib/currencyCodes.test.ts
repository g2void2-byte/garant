import { describe, expect, it } from "vitest";
import {
  normalizeCurrencyCode,
  normalizeCurrencyCodeRows,
  walletActionPath,
  walletCurrencyPath,
} from "./currencyCodes";

describe("currency code helpers", () => {
  it("normalizes ASCII currency codes", () => {
    expect(normalizeCurrencyCode(" usd ")).toBe("USD");
    expect(normalizeCurrencyCode("USDT1")).toBe("USDT1");
  });

  it("rejects path/query-breaking currency codes", () => {
    for (const value of ["", "USD/../admin", "USD?x=1", "USD&x=1", "USD-TRC20", "A".repeat(17)]) {
      expect(normalizeCurrencyCode(value)).toBeNull();
      expect(walletCurrencyPath(value)).toBeNull();
    }
  });

  it("builds encoded wallet action paths only for valid codes", () => {
    expect(walletActionPath("deposit", "usd")).toBe("/wallet/deposit?currency=USD");
    expect(walletActionPath("withdraw", "USD&provider=x")).toBe("/wallet/withdraw");
  });

  it("normalizes row codes and drops invalid or duplicate rows", () => {
    expect(
      normalizeCurrencyCodeRows([
        { code: " usd ", name: "Dollar" },
        { code: "USD", name: "Duplicate dollar" },
        { code: "USD/../admin", name: "Broken" },
        { code: "uah", name: "Hryvnia" },
      ]),
    ).toEqual([
      { code: "USD", name: "Dollar" },
      { code: "UAH", name: "Hryvnia" },
    ]);
  });
});
