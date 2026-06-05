import { formatRatingValue, parseDecimalValue, parseNonNegativeIntegerValue } from "@/lib/format";

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

export function parseAdminDecimal(value: string | number | null | undefined): number | null {
  return parseDecimalValue(value);
}

export function hasPositiveAdminDecimal(value: string | number | null | undefined): boolean {
  const parsed = parseAdminDecimal(value);
  return parsed !== null && parsed > 0;
}

export function hasVisibleAdminBalance(balance: {
  amount: string | number | null | undefined;
  locked: string | number | null | undefined;
  total: string | number | null | undefined;
}): boolean {
  const total = parseAdminDecimal(balance.total);
  if (total !== null) return total > 0;
  return hasPositiveAdminDecimal(balance.amount) || hasPositiveAdminDecimal(balance.locked);
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

export function parseAdminCount(value: unknown): number | null {
  return parseNonNegativeIntegerValue(value);
}

export function formatAdminCount(value: unknown): string {
  const parsed = parseAdminCount(value);
  return parsed === null ? DASH : String(parsed);
}

export function parseAdminId(value: unknown): number | null {
  const parsed = parseAdminCount(value);
  return parsed !== null && parsed > 0 ? parsed : null;
}

export function formatAdminId(value: unknown): string {
  const parsed = parseAdminId(value);
  return parsed === null ? DASH : String(parsed);
}

export function getAdminTotalPages(total: unknown, pageSize: unknown): number {
  const totalCount = parseAdminCount(total);
  const parsedPageSize = parseAdminCount(pageSize);
  if (totalCount === null || parsedPageSize === null || parsedPageSize <= 0) return 1;
  return Math.max(1, Math.ceil(totalCount / parsedPageSize));
}

export function shouldShowAdminPagination(total: unknown, pageSize: unknown): boolean {
  const totalCount = parseAdminCount(total);
  const parsedPageSize = parseAdminCount(pageSize);
  return totalCount !== null && parsedPageSize !== null && parsedPageSize > 0 && totalCount > parsedPageSize;
}
