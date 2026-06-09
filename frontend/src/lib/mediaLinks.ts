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
  if (hasRawWhitespaceOrControl(raw) || raw.includes("#")) return null;

  const queryStart = raw.indexOf("?");
  const path = queryStart === -1 ? raw : raw.slice(0, queryStart);
  const search = queryStart === -1 ? "" : raw.slice(queryStart);
  if (!path.startsWith("/media/")) return null;
  if (path.includes("//") || path.includes("\\") || path.includes(";")) return null;

  let decodedPath: string;
  try {
    decodedPath = decodeURIComponent(path);
  } catch {
    return null;
  }
  if (decodedPath !== path) return null;

  const origin = baseOrigin();
  try {
    const parsed = new URL(path, origin);
    if (parsed.origin !== origin) return null;
    if (parsed.pathname !== path || !parsed.pathname.startsWith("/media/")) return null;
    return `${parsed.pathname}${search}`;
  } catch {
    return null;
  }
}

export function safeUserImageUrl(url: string | null | undefined): string | null {
  const raw = url?.trim();
  if (!raw) return null;
  const media = safeMediaUrl(raw);
  if (media) return media;
  if (hasRawWhitespaceOrControl(raw) || raw.includes("\\")) return null;

  const lower = raw.toLowerCase();
  if (!lower.startsWith("https://") || raw.charAt("https://".length) === "/") return null;
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "https:" || !parsed.hostname) return null;
    if (parsed.username || parsed.password) return null;
    return raw;
  } catch {
    return null;
  }
}

function hasRawWhitespaceOrControl(value: string): boolean {
  for (const ch of value) {
    const code = ch.charCodeAt(0);
    if (code <= 0x20 || code === 0x7f) return true;
  }
  return false;
}
