import { describe, expect, it } from "vitest";
import {
  dealsLabel,
  dayKey,
  formatAmount,
  formatCountValue,
  formatCurrency,
  formatDateTime,
  formatMoney,
  formatRating,
  formatRatingValue,
  hasPositiveIntegerValue,
  parseDecimal,
  parseDateTimeMs,
  parseNonNegativeIntegerValue,
  parseRatingValue,
  relativeTime,
} from "./format";

describe("parseDecimal", () => {
  it("returns 0 for nullish input", () => {
    expect(parseDecimal(null)).toBe(0);
    expect(parseDecimal(undefined)).toBe(0);
  });

  it("returns the number unchanged when finite", () => {
    expect(parseDecimal(12.5)).toBe(12.5);
    expect(parseDecimal(0)).toBe(0);
  });

  it("returns 0 for non-finite numbers", () => {
    expect(parseDecimal(Number.NaN)).toBe(0);
    expect(parseDecimal(Number.POSITIVE_INFINITY)).toBe(0);
  });

  it("parses string-form Decimals (M-9 wire format)", () => {
    expect(parseDecimal("123.45")).toBeCloseTo(123.45);
    expect(parseDecimal("-.5")).toBeCloseTo(-0.5);
    expect(parseDecimal("0")).toBe(0);
  });

  it("returns 0 for malformed strings", () => {
    expect(parseDecimal("not-a-number")).toBe(0);
    expect(parseDecimal("")).toBe(0);
    expect(parseDecimal("1e2")).toBe(0);
    expect(parseDecimal("0x10")).toBe(0);
    expect(parseDecimal("Infinity")).toBe(0);
  });
});

describe("formatCurrency", () => {
  it("renders amount with the given code", () => {
    expect(formatCurrency("10.5", "USDT")).toBe("10.5 USDT");
  });

  it("respects the decimals argument (truncates extra digits)", () => {
    expect(formatCurrency("1.23456789", "BTC", 4)).toBe("1.2346 BTC");
  });

  it("falls back to per-currency precision for malformed decimals overrides", () => {
    expect(formatCurrency("1.2345", "USDT", "8" as unknown as number)).toBe("1.23 USDT");
    expect(formatCurrency("1.2345", "BTC", 999 as unknown as number)).toBe("1.2345 BTC");
  });

  it("falls back to 0 for malformed input", () => {
    expect(formatCurrency("oops", "USDT")).toBe("0 USDT");
  });
});

describe("parseNonNegativeIntegerValue", () => {
  it("accepts finite non-negative integers and decimal integer strings", () => {
    expect(parseNonNegativeIntegerValue(0)).toBe(0);
    expect(parseNonNegativeIntegerValue(42)).toBe(42);
    expect(parseNonNegativeIntegerValue("42")).toBe(42);
    expect(formatCountValue("7")).toBe("7");
    expect(hasPositiveIntegerValue("7")).toBe(true);
  });

  it("rejects ambiguous, unsafe and non-integer count payloads", () => {
    expect(parseNonNegativeIntegerValue("1e2")).toBeNull();
    expect(parseNonNegativeIntegerValue("0x10")).toBeNull();
    expect(parseNonNegativeIntegerValue("1.0")).toBeNull();
    expect(parseNonNegativeIntegerValue(-1)).toBeNull();
    expect(parseNonNegativeIntegerValue(true)).toBeNull();
    expect(formatCountValue("1e2")).toBe("\u2014");
    expect(hasPositiveIntegerValue("1e2")).toBe(false);
  });
});

describe("formatAmount", () => {
  it("uses per-currency default precision", () => {
    expect(formatAmount("0.123456789", "BTC")).toBe("0.12345679");
    expect(formatAmount("0.123456789", "USDT")).toBe("0.12");
  });

  it("treats unknown codes as 2 decimals", () => {
    expect(formatAmount("1.234", "FOO")).toBe("1.23");
  });
});

describe("formatMoney", () => {
  it("formats integers without decimals", () => {
    expect(formatMoney(42)).toBe("$42");
  });

  it("renders thousands with k suffix", () => {
    expect(formatMoney(1500)).toBe("$1.5k+");
    expect(formatMoney(25_000)).toBe("$25.0k");
  });

  it("renders millions with M suffix", () => {
    expect(formatMoney(2_500_000)).toBe("$2.5M");
  });

  it("returns a neutral fallback for malformed or negative values", () => {
    expect(formatMoney(Number.NaN)).toBe("\u2014");
    expect(formatMoney(-1)).toBe("\u2014");
    expect(formatMoney("-1")).toBe("\u2014");
    expect(formatMoney("oops", "n/a")).toBe("n/a");
  });

  it("parses string money values without accepting ambiguous notation", () => {
    expect(formatMoney("250.50")).toBe("$250.50");
    expect(formatMoney("1500")).toBe("$1.5k+");
    expect(formatMoney("1e3")).toBe("\u2014");
    expect(formatMoney("0x10")).toBe("\u2014");
  });
});

describe("formatRating", () => {
  it('returns "—" when there are no reviews', () => {
    expect(formatRating(4.5, 0)).toBe("—");
  });

  it("renders one decimal when there are reviews", () => {
    expect(formatRating(4.5, 12)).toBe("4.5");
  });

  it("parses string ratings and rejects malformed or out-of-range values", () => {
    expect(parseRatingValue("4.75")).toBeCloseTo(4.75);
    expect(formatRatingValue("4.75")).toBe("4.8");
    expect(formatRating("4.5", 1)).toBe("4.5");
    expect(formatRating("4.5", "1")).toBe("4.5");
    expect(formatRating(4.5, "1e2")).toBe("\u2014");
    expect(formatRating("0x5", 1)).toBe("\u2014");
    expect(formatRating("1e1", 1)).toBe("\u2014");
    expect(formatRating(6, 1)).toBe("\u2014");
  });
});

describe("dealsLabel", () => {
  it("pluralizes correctly for Russian numerals", () => {
    expect(dealsLabel(1)).toBe("1 сделка");
    expect(dealsLabel(3)).toBe("3 сделки");
    expect(dealsLabel(5)).toBe("5 сделок");
    expect(dealsLabel(11)).toBe("11 сделок");
    expect(dealsLabel(21)).toBe("21 сделка");
    expect(dealsLabel(22)).toBe("22 сделки");
  });

  it("parses string integer counts without accepting ambiguous notation", () => {
    expect(dealsLabel("22")).toBe("22 сделки");
    expect(dealsLabel("1e2")).toBe("\u2014 сделок");
    expect(dealsLabel("0x10")).toBe("\u2014 сделок");
    expect(dealsLabel(true)).toBe("\u2014 сделок");
  });
});

describe("parseDateTimeMs", () => {
  it("returns a finite timestamp for valid date strings", () => {
    expect(parseDateTimeMs("2026-01-01T00:00:00Z")).toBe(Date.UTC(2026, 0, 1));
  });

  it("returns null for missing or malformed date strings", () => {
    expect(parseDateTimeMs("not-a-date")).toBeNull();
    expect(parseDateTimeMs(null)).toBeNull();
  });
});

describe("formatDateTime", () => {
  it("returns a neutral marker for malformed timestamps", () => {
    expect(formatDateTime("not-a-date")).toBe("\u2014");
    expect(formatDateTime(null)).toBe("\u2014");
  });

  it("formats valid timestamps with caller-supplied options", () => {
    expect(
      formatDateTime("2026-01-01T00:00:00Z", {
        timeZone: "UTC",
        dateStyle: "short",
        timeStyle: "short",
      }),
    ).toMatch(/01\.01\.2026|1\.01\.2026/);
  });
});

describe("relativeTime", () => {
  it("returns a neutral marker for malformed timestamps", () => {
    expect(relativeTime("not-a-date")).toBe("\u2014");
  });

  it("formats far-future timestamps instead of treating them as fresh", () => {
    const future = new Date(Date.now() + 10 * 60 * 1000);
    expect(relativeTime(future.toISOString())).toBe(future.toLocaleDateString("ru-RU"));
  });

  it("renders short suffixes for fresh timestamps", () => {
    expect(relativeTime(new Date().toISOString())).toBe("только что");
    const tenMinAgo = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    expect(relativeTime(tenMinAgo)).toMatch(/мин назад/);
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    expect(relativeTime(twoHoursAgo)).toMatch(/ч назад/);
    const threeDaysAgo = new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString();
    expect(relativeTime(threeDaysAgo)).toMatch(/дн назад/);
  });
});

describe("dayKey", () => {
  it("returns a neutral marker for malformed timestamps", () => {
    expect(dayKey("not-a-date")).toBe("\u2014");
  });

  it("returns 'Сегодня' for today", () => {
    expect(dayKey(new Date().toISOString())).toBe("Сегодня");
  });

  it("returns 'Вчера' for yesterday", () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    expect(dayKey(yesterday.toISOString())).toBe("Вчера");
  });
});
