import { describe, expect, it } from "vitest";

import {
  formatAdminAmount,
  formatAdminCount,
  formatAdminCurrencyCode,
  formatAdminDealStatus,
  formatAdminId,
  formatAdminRating,
  formatAdminUsd,
  formatAdminUsdSuffix,
  formatAdminUsername,
  getAdminTotalPages,
  hasVisibleAdminBalance,
  parseAdminDecimal,
  pickAdminMutationCurrency,
  shouldShowAdminPagination,
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
    expect(parseAdminDecimal("12.5")).toBe(12.5);
    expect(parseAdminDecimal("1e3")).toBeNull();
    expect(formatAdminUsd("1500.5")).toBe("$1500.50");
    expect(formatAdminUsdSuffix("1500.5")).toBe("1500.50 $");
    expect(formatAdminUsd("1e3")).toBe("\u2014");
    expect(formatAdminUsdSuffix("0x10")).toBe("\u2014");
  });

  it("normalizes admin currency labels before display", () => {
    expect(formatAdminCurrencyCode(" usd ")).toBe("USD");
    expect(formatAdminCurrencyCode("USDT1")).toBe("USDT1");
    expect(formatAdminCurrencyCode("../USD")).toBe("\u2014");
    expect(formatAdminCurrencyCode(null)).toBe("\u2014");
  });

  it("formats admin deal statuses without leaking unknown runtime values", () => {
    expect(formatAdminDealStatus("in_progress")).toBe("В работе");
    expect(formatAdminDealStatus("provider_reconciled")).toBe("Статус неизвестен");
    expect(formatAdminDealStatus(null)).toBe("Статус неизвестен");
  });

  it("picks admin mutation currencies from normalized known codes", () => {
    const currencies = [{ code: "USDT" }, { code: "TON" }];
    expect(pickAdminMutationCurrency(" ton ", currencies)).toBe("TON");
    expect(pickAdminMutationCurrency("../TON", currencies)).toBe("USDT");
    expect(pickAdminMutationCurrency("USDC", currencies, " ton ")).toBe("TON");
    expect(pickAdminMutationCurrency("../TON", [])).toBe("USDT");
  });

  it("keeps admin balances visible when malformed totals have valid money fields", () => {
    expect(hasVisibleAdminBalance({ amount: "0", locked: "0", total: "0" })).toBe(false);
    expect(hasVisibleAdminBalance({ amount: "25", locked: "0", total: "1e2" })).toBe(true);
    expect(hasVisibleAdminBalance({ amount: "0", locked: "5", total: "0x10" })).toBe(true);
    expect(hasVisibleAdminBalance({ amount: "1e2", locked: "0", total: "0x10" })).toBe(false);
  });

  it("formats string ratings and rejects malformed or out-of-range values", () => {
    expect(formatAdminRating("4.75")).toBe("4.8");
    expect(formatAdminRating("1e1")).toBe("\u2014");
    expect(formatAdminRating(6)).toBe("\u2014");
  });

  it("parses admin counters strictly before display and pagination math", () => {
    expect(formatAdminCount("42")).toBe("42");
    expect(formatAdminCount("1e2")).toBe("\u2014");
    expect(formatAdminCount("0x10")).toBe("\u2014");
    expect(getAdminTotalPages("100", "20")).toBe(5);
    expect(getAdminTotalPages("1e2", 20)).toBe(1);
    expect(getAdminTotalPages(100, "0")).toBe(1);
    expect(shouldShowAdminPagination("100", 20)).toBe(true);
    expect(shouldShowAdminPagination("1e2", 20)).toBe(false);
  });

  it("formats positive admin identifiers without accepting count sentinels", () => {
    expect(formatAdminId("42")).toBe("42");
    expect(formatAdminId(0)).toBe("\u2014");
    expect(formatAdminId("1e2")).toBe("\u2014");
  });
});
