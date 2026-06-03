const FALLBACK_ORIGIN = "https://garant.local";

function baseOrigin(): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return FALLBACK_ORIGIN;
}

export function safeMediaUrl(url: string | null | undefined): string | null {
  const raw = url?.trim();
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return null;

  const origin = baseOrigin();
  try {
    const parsed = new URL(raw, origin);
    if (parsed.origin !== origin) return null;
    if (!parsed.pathname.startsWith("/media/")) return null;
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return null;
  }
}
