import { motion, useScroll, useTransform } from "framer-motion";
import { useRef } from "react";
import type { UserCardDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { Logo } from "@/components/layout/Logo";

export function ProfileHeader({ user }: { user: UserCardDto }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollY } = useScroll();
  const y = useTransform(scrollY, [0, 200], [0, -40]);
  const opacity = useTransform(scrollY, [0, 220], [1, 0.4]);

  return (
    <div ref={ref} className="relative">
      <motion.div
        style={{ y, opacity, backgroundImage: user.banner_url ? `url(${user.banner_url})` : undefined }}
        className="relative h-44 rounded-b-3xl overflow-hidden bg-gradient-to-br from-accent/20 via-panel-2 to-panel bg-cover bg-center"
      >
        {!user.banner_url && (
          <div className="absolute inset-0 grid place-items-center">
            <Logo size={72} />
          </div>
        )}
      </motion.div>

      <div className="-mt-12 px-4 flex items-end gap-3">
        <div className="relative">
          <Avatar
            name={user.username}
            size={88}
            className="ring-4 ring-bg glow-accent"
          />
        </div>
        <div className="flex-1 min-w-0 pb-2">
          <div className="flex items-center gap-2 flex-wrap">
            <BadgePrefix prefix={user.prefix} />
            <span className="font-bold text-lg truncate">@{user.username}</span>
          </div>
          {user.description && <div className="mt-1 text-sm text-text-muted line-clamp-2">{user.description}</div>}
        </div>
      </div>
    </div>
  );
}
