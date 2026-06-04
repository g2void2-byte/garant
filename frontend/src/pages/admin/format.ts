import { formatRatingValue, parseDecimalValue } from "@/lib/format";

const MISSING_USERNAME_LABEL = "username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d";
const DASH = "\u2014";

export function formatAdminUsername(username: string | null | undefined): string {
  const trimmed = username?.trim();
  return trimmed ? `@${trimmed}` : MISSING_USERNAME_LABEL;
}

export function formatAdminFixedDecimal(
  value: string | number | null | undefined,
  decimals: number,
): string {
  if (!Number.isInteger(decimals) || decimals < 0 || decimals > 20) return DASH;
  const parsed = parseDecimalValue(value);
  return parsed === null ? DASH : parsed.toFixed(decimals);
}

export function formatAdminAmount(
  value: string | number | null | undefined,
  decimals = 2,
): string {
  return formatAdminFixedDecimal(value, decimals);
}

export function formatAdminUsd(value: string | number | null | undefined): string {
  const fixed = formatAdminFixedDecimal(value, 2);
  return fixed === DASH ? DASH : `$${fixed}`;
}

export function formatAdminUsdSuffix(value: string | number | null | undefined): string {
  const fixed = formatAdminFixedDecimal(value, 2);
  return fixed === DASH ? DASH : `${fixed} $`;
}

export function formatAdminRating(value: string | number | null | undefined): string {
  return formatRatingValue(value);
}
