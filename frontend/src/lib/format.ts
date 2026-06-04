const DECIMAL_STRING_RE = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/;

export function parseDecimalValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const trimmed = value.trim();
  if (!DECIMAL_STRING_RE.test(trimmed)) return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

export function parseDecimal(value: string | number | null | undefined): number {
  return parseDecimalValue(value) ?? 0;
}

const DEFAULT_DECIMALS: Record<string, number> = {
  USDT: 2,
  USDC: 2,
  BTC: 8,
  ETH: 6,
  TON: 4,
  LTC: 6,
  BNB: 6,
  TRX: 4,
  DOGE: 4,
  SOL: 6,
};
const MAX_DISPLAY_DECIMALS = 20;

// Resolve the display precision when a caller did not pass an
// explicit ``decimals``. Falls back to the per-currency table above
// (BTC → 8, USDT → 2, …) so e.g. ``formatCurrency(0.12345678, "BTC")``
// no longer rounds to ``0.12 BTC`` and silently hides 6 fractional
// digits of a user's balance. The legacy fallback of a flat ``2``
// remains for unknown / fiat codes the table doesn't cover (RUB,
// USD, etc.) — those have at most 2 meaningful fractional digits
// anyway, so the previous behaviour is preserved.
export function resolveDisplayDecimals(code: string, override?: number): number {
  if (
    typeof override === "number" &&
    Number.isInteger(override) &&
    override >= 0 &&
    override <= MAX_DISPLAY_DECIMALS
  ) {
    return override;
  }
  return DEFAULT_DECIMALS[code.toUpperCase()] ?? 2;
}

export function formatCurrency(
  value: number | string | null | undefined,
  code: string,
  decimals?: number,
): string {
  const n = parseDecimal(value);
  if (!Number.isFinite(n)) return `0 ${code}`;
  const fixed = n.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: resolveDisplayDecimals(code, decimals),
  });
  return `${fixed} ${code}`;
}

export function formatAmount(
  value: number | string | null | undefined,
  code: string,
): string {
  const n = parseDecimal(value);
  if (!Number.isFinite(n)) return "0";
  const decimals = DEFAULT_DECIMALS[code.toUpperCase()] ?? 2;
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
}

export function formatMoney(value: number | string | null | undefined): string {
  const n = parseDecimal(value);
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `$${(n / 1000).toFixed(1)}k`;
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}k+`;
  if (Number.isInteger(n)) return `$${n}`;
  return `$${n.toFixed(2)}`;
}

export function parseRatingValue(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const parsed = parseDecimalValue(value);
  if (parsed === null || parsed < 0 || parsed > 5) return null;
  return parsed;
}

export function formatRatingValue(value: string | number | null | undefined): string {
  const rating = parseRatingValue(value);
  return rating === null ? "\u2014" : rating.toFixed(1);
}

export function formatRating(rating: string | number | null | undefined, count: number): string {
  if (!count) return "—";
  return formatRatingValue(rating);
}

export function parseDateTimeMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const ts = new Date(value).getTime();
  return Number.isFinite(ts) ? ts : null;
}

function parseDate(value: string | null | undefined): Date | null {
  const ts = parseDateTimeMs(value);
  return ts === null ? null : new Date(ts);
}

export function formatDateTime(
  value: string | null | undefined,
  options?: Intl.DateTimeFormatOptions,
): string {
  const date = parseDate(value);
  return date ? date.toLocaleString("ru-RU", options) : "\u2014";
}

export function dealsLabel(count: number): string {
  if (count % 10 === 1 && count % 100 !== 11) return `${count} сделка`;
  if (count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14)) return `${count} сделки`;
  return `${count} сделок`;
}

export function relativeTime(iso: string): string {
  const date = parseDate(iso);
  if (!date) return "\u2014";
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < -60) return date.toLocaleDateString("ru-RU");
  if (diff < 60) return "только что";
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} дн назад`;
  return date.toLocaleDateString("ru-RU");
}

export function dayKey(iso: string): string {
  const d = parseDate(iso);
  if (!d) return "\u2014";
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const isSameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (isSameDay(d, today)) return "Сегодня";
  if (isSameDay(d, yesterday)) return "Вчера";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}
