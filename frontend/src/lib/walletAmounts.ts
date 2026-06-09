import type { WalletBalanceDto } from "@/api/types";
import { formatCurrency, parseDecimalValue } from "@/lib/format";

type WalletBalanceDecimalField = "amount" | "locked" | "total";

function walletBalanceStringField(field: WalletBalanceDecimalField): keyof WalletBalanceDto {
  if (field === "amount") return "amount_str";
  if (field === "locked") return "locked_str";
  return "total_str";
}

export function walletBalanceDecimalInput(
  balance: WalletBalanceDto,
  field: WalletBalanceDecimalField,
): string | null {
  const stringValue = balance[walletBalanceStringField(field)];
  const raw =
    typeof stringValue === "string" && stringValue.trim()
      ? stringValue.trim()
      : String(balance[field] ?? "").trim();
  return parseDecimalValue(raw) === null ? null : raw;
}

export function parseWalletBalanceDecimal(
  balance: WalletBalanceDto | null | undefined,
  field: WalletBalanceDecimalField,
): number | null {
  if (!balance) return null;
  const raw = walletBalanceDecimalInput(balance, field);
  return raw === null ? null : parseDecimalValue(raw);
}

export function hasPositiveWalletBalance(
  balance: WalletBalanceDto | null | undefined,
  field: WalletBalanceDecimalField,
): boolean {
  const parsed = parseWalletBalanceDecimal(balance, field);
  return parsed !== null && parsed > 0;
}

export function formatWalletBalanceCurrency(
  balance: WalletBalanceDto | null | undefined,
  field: WalletBalanceDecimalField,
  code: string,
  decimals?: number,
  fallback = "\u2014",
): string {
  if (!balance) return formatCurrency(0, code, decimals);
  const raw = walletBalanceDecimalInput(balance, field);
  const parsed = raw === null ? null : parseDecimalValue(raw);
  if (parsed === null || parsed < 0) return `${fallback} ${code}`;
  return formatCurrency(raw, code, decimals);
}
