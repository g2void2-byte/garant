import { Star } from "lucide-react";
import { Link } from "react-router-dom";
import type { UserCardDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { OnlineDot } from "@/components/ui/OnlineDot";
import { formatMoney, dealsLabel } from "@/lib/format";
import { staggerDelay } from "@/lib/animate";
import { countryFromCode } from "@/lib/countries";

export function UserCard({ user, index = 0 }: { user: UserCardDto; index?: number }) {
  const name = user.display_name?.trim() || user.username || "—";
  const country = countryFromCode(user.country);
  const ratingLabel = user.reviews_count ? user.rating.toFixed(1) : "0.0";
  return (
    <div
      className="animate-fadein"
      style={staggerDelay(index)}
    >
      <Link
        to={`/users/${user.username}`}
        className="flex items-center gap-3 bg-panel border border-border rounded-card p-3.5 active:scale-[.99] transition-transform"
      >
        <div className="relative">
          <Avatar name={user.username} src={user.photo_url} size={52} />
          <span className="absolute -bottom-0.5 -right-0.5 ring-2 ring-panel rounded-full">
            <OnlineDot online={user.online} />
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <BadgePrefix prefix={user.prefix} />
            <span className="font-semibold text-[15px] leading-tight truncate">{name}</span>
            {country && (
              <span
                aria-label={country.name}
                title={country.name}
                className="shrink-0 text-base leading-none"
              >
                {country.flag}
              </span>
            )}
          </div>
          <div className="mt-1 text-[13px] text-text-muted truncate">@{user.username}</div>
        </div>
        <div className="flex flex-col items-end shrink-0 gap-1">
          <div className="flex items-center gap-2.5 leading-none">
            <span className="inline-flex items-center gap-1 text-accent text-[13px] font-semibold">
              <Star className="size-3.5" strokeWidth={2.5} />
              {ratingLabel}
            </span>
            <span className="text-accent text-[13px] font-semibold tabular-nums">
              {formatMoney(user.deposit)}
            </span>
          </div>
          <div className="text-[12px] text-text-muted tabular-nums">
            {dealsLabel(user.deals_count)}
          </div>
        </div>
      </Link>
    </div>
  );
}
