import { Star } from "lucide-react";
import { Link } from "react-router-dom";
import type { UserCardDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { OnlineDot } from "@/components/ui/OnlineDot";
import { formatMoney, dealsLabel, formatRatingValue } from "@/lib/format";
import { staggerDelay } from "@/lib/animate";
import { countryFromCode } from "@/lib/countries";
import { normalizeUsernameRef, userProfilePath } from "@/lib/usernames";

export function UserCard({ user, index = 0 }: { user: UserCardDto; index?: number }) {
  const username = normalizeUsernameRef(user.username);
  const profilePath = userProfilePath(username);
  const name = user.display_name?.trim() || username || "—";
  const country = countryFromCode(user.country);
  const ratingLabel = user.reviews_count ? formatRatingValue(user.rating) : "0.0";
  const body = (
    <>
      <div className="relative shrink-0">
        <Avatar name={name} src={user.photo_url} size={56} />
        <span className="absolute -bottom-0.5 -right-0.5 ring-2 ring-panel rounded-full">
          <OnlineDot online={user.online} />
        </span>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <BadgePrefix prefix={user.prefix} />
          <span className="font-semibold text-base leading-snug truncate">{name}</span>
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
        <div className="mt-1 text-[13px] text-text-muted truncate">
          {username ? `@${username}` : "username не задан"}
        </div>
      </div>
      <div className="flex flex-col items-end shrink-0 gap-1.5">
        <div className="flex items-center gap-3 leading-none">
          <span className="inline-flex items-center gap-1 text-accent text-sm font-semibold">
            <Star className="size-3.5" strokeWidth={2.5} />
            {ratingLabel}
          </span>
          <span className="text-accent text-sm font-semibold tabular-nums">
            {formatMoney(user.deposit)}
          </span>
        </div>
        <div className="text-xs text-text-muted tabular-nums">
          {dealsLabel(user.deals_count)}
        </div>
      </div>
    </>
  );
  return (
    <div
      className="animate-fadein"
      style={staggerDelay(index)}
    >
      {profilePath ? (
        <Link
          to={profilePath}
          className="flex items-center gap-3.5 bg-panel border border-border rounded-card p-4 active:scale-[.99] transition-transform"
        >
          {body}
        </Link>
      ) : (
        <div className="flex items-center gap-3.5 bg-panel border border-border rounded-card p-4">
          {body}
        </div>
      )}
    </div>
  );
}
