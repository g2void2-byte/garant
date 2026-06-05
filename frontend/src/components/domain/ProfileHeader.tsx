import { useRef, useEffect, useState, useCallback } from "react";
import type { UserCardDto } from "@/api/types";
import { Logo } from "@/components/layout/Logo";
import { Avatar } from "@/components/ui/Avatar";
import { countryFromCode } from "@/lib/countries";
import { safeUserImageUrl } from "@/lib/mediaLinks";
import { getTelegramUser } from "@/lib/tg";
import { normalizeUsernameRef } from "@/lib/usernames";
import { cn } from "@/lib/cn";

// Keep keys in lockstep with ``UserCardDto.prefix`` on the backend
// (``backend/app/serializers._common_user_fields``). The ``vip`` entry
// used to be missing here, which is why a user with ``is_vip=true``
// got an empty pill instead of the badge.
const ROLE_LABEL: Record<NonNullable<UserCardDto["prefix"]>, string> = {
  admin: "Админ",
  arbiter: "Арбитр",
  vip: "VIP",
};
const UNKNOWN_ROLE_LABEL = "Роль неизвестна";

export function ProfileHeader({ user }: { user: UserCardDto }) {
  const ref = useRef<HTMLDivElement>(null);
  const [transform, setTransform] = useState({ y: 0, opacity: 1 });

  const onScroll = useCallback(() => {
    const scrollY = window.scrollY;
    const t = Math.min(1, Math.max(0, scrollY / 200));
    setTransform({
      y: -40 * t,
      opacity: 1 - 0.6 * Math.min(1, scrollY / 220),
    });
  }, []);

  useEffect(() => {
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [onScroll]);

  const username = normalizeUsernameRef(user.username);
  const displayName = user.display_name?.trim() || username || "—";
  const knownRoleLabel = user.prefix ? ROLE_LABEL[user.prefix] : null;
  const roleLabel = user.prefix
    ? knownRoleLabel ?? UNKNOWN_ROLE_LABEL
    : "Пользователь";
  const roleClassName = user.prefix && !knownRoleLabel
    ? "bg-panel-2 text-text-muted"
    : "bg-accent text-accent-fg";
  const country = countryFromCode(user.country);
  // V12-UI — the avatar circle is sourced from the Telegram user's
  // ``photo_url`` (exposed via ``initDataUnsafe`` for the *current*
  // viewer). When viewing your own profile we always have it; for
  // someone else's profile we fall back to ``user.photo_url`` from
  // the backend (which may be null). ``Avatar`` renders the first
  // letter of the display name when no URL is available.
  //
  // Audit (continuation) M-4 — pre-fix the "is this my own profile?"
  // check compared by ``username``. That's unstable because Telegram
  // usernames can be changed, and ``deps.get_current_user`` only
  // syncs the new value through after the next REST call lands the
  // ``user.username = tg_user["username"]`` write. During the race
  // window an "anonymous Telegram user with a brand-new username"
  // would compare unequal to themselves and miss the avatar
  // fallback. ``tg_user_id`` is immutable per Telegram account and
  // is exposed on every ``UserCardDto`` via ``user_id``, so the
  // comparison below is stable across rename races.
  const tgUser = getTelegramUser();
  const isMe = tgUser?.id === user.user_id;
  const avatarSrc = user.photo_url || (isMe ? tgUser?.photo_url : null);
  const bannerSrc = safeUserImageUrl(user.banner_url);

  return (
    <div ref={ref}>
      <div
        style={{
          transform: `translateY(${transform.y}px)`,
          opacity: transform.opacity,
        }}
        className="relative h-64 mx-4 mt-3 rounded-3xl overflow-hidden bg-gradient-to-br from-accent/20 via-panel-2 to-panel bg-cover bg-center will-change-transform"
      >
        {bannerSrc && (
          <img
            src={bannerSrc}
            alt=""
            aria-hidden="true"
            data-testid="profile-banner-image"
            className="absolute inset-0 size-full object-cover"
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
          />
        )}
        {!bannerSrc && (
          <div className="absolute inset-0 grid place-items-center">
            <Logo size={96} />
          </div>
        )}
      </div>

      <div className="px-4 -mt-10 relative">
        <div className="bg-panel border border-border rounded-card p-4">
          <div className="flex items-center gap-3.5">
            <Avatar
              name={displayName}
              src={avatarSrc}
              size={72}
              className="ring-4 ring-bg shadow-pop"
            />
            <div className="min-w-0 flex-1">
              <h1 className="text-xl font-bold leading-tight truncate">{displayName}</h1>
              <div className="mt-1 text-[13px] text-text-muted truncate">
                {username ? `@${username}` : "username не задан"}
              </div>
              {country && (
                <div className="mt-0.5 text-[13px] text-text-muted truncate">
                  <span aria-hidden>{country.flag}</span> {country.name}
                </div>
              )}
              <div className="mt-1 text-xs text-text-muted">ID: {user.user_id}</div>
            </div>
            <span
              className={cn(
                "self-start inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-semibold leading-none shrink-0",
                roleClassName,
              )}
            >
              {roleLabel}
            </span>
          </div>

          <div className="mt-4 border-t border-border pt-3">
            <div className="text-xs text-text-muted">Описание</div>
            <div className="mt-1 text-sm whitespace-pre-line break-words">
              {user.description?.trim() || (
                <span className="text-text-muted">Нет описания</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
