const TELEGRAM_USERNAME_RE = /^@?[A-Za-z0-9_]+$/;

export function buildTelegramUserUrl(
  username: string | null | undefined,
  options: { text?: string } = {},
): string | null {
  const trimmed = username?.trim();
  if (!trimmed) return null;

  const normalized = trimmed.startsWith("@") ? trimmed.slice(1) : trimmed;
  if (!normalized || !TELEGRAM_USERNAME_RE.test(normalized)) return null;

  const url = new URL(`https://t.me/${normalized}`);
  const text = options.text?.trim();
  if (text) url.searchParams.set("text", text);
  return url.toString();
}
