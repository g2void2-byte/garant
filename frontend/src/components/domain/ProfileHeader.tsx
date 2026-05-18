import { useRef, useEffect, useState, useCallback } from "react";
import type { UserCardDto } from "@/api/types";
import { Logo } from "@/components/layout/Logo";
import { Avatar } from "@/components/ui/Avatar";
import { countryFromCode } from "@/lib/countries";
import { getTelegramUser } from "@/lib/tg";

const ROLE_LABEL: Record<string, string> = {
  admin: "Админ",
  arbiter: "Арбитр",
};

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

  const displayName = user.display_name?.trim() || user.username || "—";
  const roleLabel = user.prefix ? ROLE_LABEL[user.prefix] : "Пользователь";
  const country = countryFromCode(user.country);
  // V12-UI — the avatar circle is sourced from the Telegram user's
  // ``photo_url`` (exposed via ``initDataUnsafe`` for the *current*
  // viewer). When viewing your own profile we always have it; for
  // someone else's profile we fall back to ``user.photo_url`` from
  // the backend (which may be null). ``Avatar`` renders the first
  // letter of the display name when no URL is available.
  const tgUser = getTelegramUser();
  const avatarSrc = user.photo_url || (tgUser?.username === user.username ? tgUser?.photo_url : null);

  return (
    <div ref={ref}>
      <div
        style={{
          transform: `translateY(${transform.y}px)`,
          opacity: transform.opacity,
          backgroundImage: user.banner_url ? `url(${user.banner_url})` : undefined,
        }}
        className="relative h-64 mx-4 mt-3 rounded-3xl overflow-hidden bg-gradient-to-br from-accent/20 via-panel-2 to-panel bg-cover bg-center will-change-transform"
      >
        {!user.banner_url && (
          <div className="absolute inset-0 grid place-items-center">
            <Logo size={96} />
          </div>
        )}
      </div>

      <div className="px-4 -mt-10 relative">
        <div className="bg-panel border border-border rounded-card p-4 pt-10">
          <div className="absolute -top-2 left-7">
            <Avatar
              name={displayName}
              src={avatarSrc}
              size={64}
              className="ring-4 ring-bg shadow-pop"
            />
          </div>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h1 className="text-2xl font-bold truncate">{displayName}</h1>
              <div className="mt-0.5 text-[13px] text-text-muted truncate">@{user.username}</div>
              {country && (
                <div className="mt-0.5 text-[13px] text-text-muted truncate">
                  <span aria-hidden>{country.flag}</span> {country.name}
                </div>
              )}
              <div className="mt-1 text-xs text-text-muted">ID: {user.user_id}</div>
            </div>
            <span className="inline-flex items-center px-2.5 py-1 rounded-full bg-accent text-accent-fg text-[11px] font-semibold leading-none shrink-0">
              {roleLabel}
            </span>
          </div>

          <div className="mt-3 border-t border-border pt-3">
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
