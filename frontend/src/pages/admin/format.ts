const MISSING_USERNAME_LABEL = "username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d";

export function formatAdminUsername(username: string | null | undefined): string {
  const trimmed = username?.trim();
  return trimmed ? `@${trimmed}` : MISSING_USERNAME_LABEL;
}
