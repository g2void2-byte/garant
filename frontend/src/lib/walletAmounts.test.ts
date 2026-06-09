import { describe, expect, it } from "vitest";
import type { WalletBalanceDto } from "@/api/types";
import {
  formatWalletBalanceCurrency,
  hasPositiveWalletBalance,
  parseWalletBalanceDecimal,
  walletBalanceDecimalInput,
} from "./walletAmounts";

function makeBalance(over: Partial<WalletBalanceDto> = {}): WalletBalanceDto {
  return {
    currency: {
      id: 1,
      code: "USD",
      name: "US Dollar",
      network: "",
      icon_url: "",
      decimals: 2,
      min_deposit: 1,
      min_withdraw: 1,
      kind: "fiat",
    },
    amount: 10,
    locked: 0,
    total: 10,
    updated_at: null,
    amount_str: "10",
    locked_str: "0",
    total_str: "10",
    ...over,
  };
}

describe("wallet amount helpers", () => {
  it("prefers canonical string mirrors over runtime number fields", () => {
    const balance = makeBalance({
      amount: "1e2" as unknown as number,
      amount_str: "25.5",
    });

    expect(walletBalanceDecimalInput(balance, "amount")).toBe("25.5");
    expect(parseWalletBalanceDecimal(balance, "amount")).toBe(25.5);
    expect(formatWalletBalanceCurrency(balance, "amount", "USD", 2)).toBe("25.5 USD");
  });

  it("rejects malformed and negative runtime balance values", () => {
    const malformed = makeBalance({
      amount: "1e2" as unknown as number,
      amount_str: "1e2",
      locked: -1,
      locked_str: "-1",
    });

    expect(walletBalanceDecimalInput(malformed, "amount")).toBeNull();
    expect(parseWalletBalanceDecimal(malformed, "amount")).toBeNull();
    expect(hasPositiveWalletBalance(malformed, "locked")).toBe(false);
    expect(formatWalletBalanceCurrency(malformed, "amount", "USD", 2)).toBe("\u2014 USD");
    expect(formatWalletBalanceCurrency(malformed, "locked", "USD", 2)).toBe("\u2014 USD");
  });

  it("renders a missing balance as zero for empty wallet rows", () => {
    expect(formatWalletBalanceCurrency(undefined, "amount", "USD", 2)).toBe("0 USD");
  });
});
