const CURRENCY_CODE_RE = /^[A-Z0-9]{1,16}$/;

export function normalizeCurrencyCode(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const code = value.trim().toUpperCase();
  return CURRENCY_CODE_RE.test(code) ? code : null;
}

export function normalizeCurrencyCodeRows<T extends { code: string }>(
  rows: readonly T[],
): T[] {
  const seen = new Set<string>();
  const normalized: T[] = [];
  for (const row of rows) {
    const code = normalizeCurrencyCode(row.code);
    if (!code || seen.has(code)) continue;
    seen.add(code);
    normalized.push({ ...row, code });
  }
  return normalized;
}

export function walletCurrencyPath(value: unknown): string | null {
  const code = normalizeCurrencyCode(value);
  return code ? `/wallet/${code}` : null;
}

export function walletActionPath(action: "deposit" | "withdraw", value: unknown): string {
  const code = normalizeCurrencyCode(value);
  if (!code) return `/wallet/${action}`;
  return `/wallet/${action}?${new URLSearchParams({ currency: code }).toString()}`;
}
