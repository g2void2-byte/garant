const UNSIGNED_DECIMAL_RE = /^(?:\d+(?:\.\d+)?|\.\d+)$/;
const SIGNED_DECIMAL_RE = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$/;

function isFiniteSafeNumber(value: number): boolean {
  return Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER;
}

export function parsePositiveDecimalInput(raw: string): number | null {
  const value = raw.trim();
  if (!UNSIGNED_DECIMAL_RE.test(value)) return null;
  const parsed = Number(value);
  return isFiniteSafeNumber(parsed) && parsed > 0 ? parsed : null;
}

export function parseNonNegativeDecimalInput(raw: string): number | null {
  const value = raw.trim();
  if (!UNSIGNED_DECIMAL_RE.test(value)) return null;
  const parsed = Number(value);
  return isFiniteSafeNumber(parsed) && parsed >= 0 ? parsed : null;
}

export function parseSignedNonZeroDecimalInput(raw: string): number | null {
  const value = raw.trim();
  if (!SIGNED_DECIMAL_RE.test(value)) return null;
  const parsed = Number(value);
  return isFiniteSafeNumber(parsed) && parsed !== 0 ? parsed : null;
}

export function parseSignedDecimalInput(raw: string): number | null {
  const value = raw.trim();
  if (!SIGNED_DECIMAL_RE.test(value)) return null;
  const parsed = Number(value);
  return isFiniteSafeNumber(parsed) ? parsed : null;
}

export function parseNonNegativeIntInput(raw: string, max?: number): number | null {
  const value = raw.trim();
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 0) return null;
  if (max !== undefined && parsed > max) return null;
  return parsed;
}
