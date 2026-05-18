import { Link2 } from "lucide-react";
import type { UserCardDto } from "@/api/types";
import { openExternalLink } from "@/lib/tg";

/**
 * V12-UI — read-only forum list rendered on every profile (own + public).
 *
 * The forum collection lives on ``UserCardDto.forums`` (populated by
 * ``user_to_out``) and stores ``{name, url}`` pairs the user entered via
 * the "Добавление форума" page. We surface it as a compact list of
 * tappable rows so anyone viewing the profile can jump to the user's
 * darknet reputation pages — clicking a row opens the link in the
 * Telegram in-app browser (``openExternalLink`` → ``openLink``).
 *
 * Hidden entirely when the user has no forums to keep the profile lean.
 */
export function ProfileForumsCard({ user }: { user: UserCardDto }) {
  const forums = user.forums || [];
  if (!forums.length) return null;
  return (
    <div className="bg-panel border border-border rounded-card p-3 space-y-2">
      <div className="text-[13px] font-semibold text-text-muted px-1">Форумы</div>
      <ul className="space-y-1.5">
        {forums.map((f, i) => (
          <li key={`${f.name}-${i}`}>
            <button
              type="button"
              onClick={() => openExternalLink(f.url)}
              className="w-full flex items-center gap-3 p-2 rounded-button bg-panel-2/40 active:bg-panel-2 transition-colors text-left"
            >
              <span className="size-8 grid place-items-center rounded-full bg-panel-2 text-accent shrink-0">
                <Link2 className="size-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold truncate">{f.name}</span>
                <span className="block text-[12px] text-text-muted truncate">{f.url}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
