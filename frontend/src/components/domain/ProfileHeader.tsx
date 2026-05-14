import { motion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";
import type { UserCardDto } from "@/api/types";
import { Logo } from "@/components/layout/Logo";

const ROLE_LABEL: Record<string, string> = {
  admin: "Админ",
  arbiter: "Арбитр",
};

export function ProfileHeader({ user }: { user: UserCardDto }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollY } = useScroll();
  const y = useTransform(scrollY, [0, 200], [0, -40]);
  const opacity = useTransform(scrollY, [0, 220], [1, 0.4]);

  const displayName = user.display_name?.trim() || user.username || "—";
  const roleLabel = user.prefix ? ROLE_LABEL[user.prefix] : "Пользователь";

  return (
    <div ref={ref}>
      <motion.div
        style={{
          y,
          opacity,
          backgroundImage: user.banner_url ? `url(${user.banner_url})` : undefined,
        }}
        className="relative h-64 mx-4 mt-3 rounded-3xl overflow-hidden bg-gradient-to-br from-accent/20 via-panel-2 to-panel bg-cover bg-center"
      >
        {!user.banner_url && (
          <div className="absolute inset-0 grid place-items-center">
            <Logo size={96} />
          </div>
        )}
      </motion.div>

      <div className="px-4 mt-3">
        <div className="bg-panel border border-border rounded-card p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h1 className="text-2xl font-bold truncate">{displayName}</h1>
              <div className="mt-0.5 text-sm text-text-muted truncate">@{user.username}</div>
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
