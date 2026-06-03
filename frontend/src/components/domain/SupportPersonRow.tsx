import { ExternalLink } from "lucide-react";
import type { SupportPersonDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { openTelegramLink } from "@/lib/tg";
import { staggerDelay } from "@/lib/animate";
import { cn } from "@/lib/cn";

export function SupportPersonRow({ person, index = 0 }: { person: SupportPersonDto; index?: number }) {
  const username = person.username?.trim() || null;
  const name = person.display_name?.trim() || username || "—";
  return (
    <button
      onClick={() => username && openTelegramLink(`https://t.me/${username}`)}
      disabled={!username}
      className={cn(
        "w-full flex items-center gap-3 bg-panel border border-border rounded-card p-3 text-left transition-transform animate-fadein",
        username ? "active:scale-[0.98]" : "opacity-75",
      )}
      style={staggerDelay(index, 40, 300)}
    >
      <Avatar name={name} src={person.photo_url} size={44} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <BadgePrefix prefix={person.prefix} />
          <span className="font-semibold truncate">{name}</span>
        </div>
        <div className="mt-0.5 text-xs text-text-muted truncate">
          {username ? `@${username}` : "Telegram недоступен"}
        </div>
      </div>
      {username && <ExternalLink className="size-4 text-text-muted" />}
    </button>
  );
}
