const DECIMAL_STRING_RE = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/;

export function parseDecimal(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const trimmed = value.trim();
  if (!DECIMAL_STRING_RE.test(trimmed)) return 0;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : 0;
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

// Resolve the display precision when a caller did not pass an
// explicit ``decimals``. Falls back to the per-currency table above
// (BTC → 8, USDT → 2, …) so e.g. ``formatCurrency(0.12345678, "BTC")``
// no longer rounds to ``0.12 BTC`` and silently hides 6 fractional
// digits of a user's balance. The legacy fallback of a flat ``2``
// remains for unknown / fiat codes the table doesn't cover (RUB,
// USD, etc.) — those have at most 2 meaningful fractional digits
// anyway, so the previous behaviour is preserved.
function _displayDecimals(code: string, override?: number): number {
  if (override !== undefined) return override;
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
    maximumFractionDigits: _displayDecimals(code, decimals),
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

export function formatMoney(value: number): string {
  if (!Number.isFinite(value)) return "$0";
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 10_000) return `$${(value / 1000).toFixed(1)}k`;
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}k+`;
  if (Number.isInteger(value)) return `$${value}`;
  return `$${value.toFixed(2)}`;
}

export function formatRating(rating: number, count: number): string {
  if (!count) return "—";
  return rating.toFixed(1);
}

export function dealsLabel(count: number): string {
  if (count % 10 === 1 && count % 100 !== 11) return `${count} сделка`;
  if (count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 12 || count % 100 > 14)) return `${count} сделки`;
  return `${count} сделок`;
}

export function relativeTime(iso: string): string {
  const date = new Date(iso);
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 60) return "только что";
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} дн назад`;
  return date.toLocaleDateString("ru-RU");
}

export function dayKey(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const isSameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (isSameDay(d, today)) return "Сегодня";
  if (isSameDay(d, yesterday)) return "Вчера";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}
