const USERNAME_REF_RE = /^[A-Za-z0-9_-]{1,64}$/;

export function normalizeUsernameRef(value: string | null | undefined): string | null {
  const trimmed = value?.trim().replace(/^@+/, "").trim();
  if (!trimmed || !USERNAME_REF_RE.test(trimmed)) return null;
  return trimmed;
}

export function userProfilePath(username: string | null | undefined): string | null {
  const normalized = normalizeUsernameRef(username);
  return normalized ? `/users/${encodeURIComponent(normalized)}` : null;
}

export function createDealPath(username: string | null | undefined): string | null {
  const normalized = normalizeUsernameRef(username);
  return normalized ? `/create-deal/${encodeURIComponent(normalized)}` : null;
}

export function newDealToPath(username: string | null | undefined): string | null {
  const normalized = normalizeUsernameRef(username);
  if (!normalized) return null;
  return `/deals/new?${new URLSearchParams({ to: normalized }).toString()}`;
}

export function userDetailApiPath(username: string | null | undefined): string | null {
  const normalized = normalizeUsernameRef(username);
  return normalized ? `api/users/${encodeURIComponent(normalized)}` : null;
}
