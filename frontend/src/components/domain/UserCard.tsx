import { motion } from "framer-motion";
import { Star } from "lucide-react";
import { Link } from "react-router-dom";
import type { UserCardDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { OnlineDot } from "@/components/ui/OnlineDot";
import { formatMoney, dealsLabel } from "@/lib/format";

export function UserCard({ user, index = 0 }: { user: UserCardDto; index?: number }) {
  const name = user.display_name?.trim() || user.username || "—";
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.03, 0.3), duration: 0.2 }}
    >
      <Link
        to={`/users/${user.username}`}
        className="flex items-center gap-3 bg-panel border border-border rounded-card p-3 active:scale-[.99] transition-transform"
      >
        <div className="relative">
          <Avatar name={user.username} src={user.photo_url} size={48} />
          <span className="absolute -bottom-0.5 -right-0.5 ring-2 ring-panel rounded-full">
            <OnlineDot online={user.online} />
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <BadgePrefix prefix={user.prefix} />
            <span className="font-semibold truncate">{name}</span>
          </div>
          <div className="mt-0.5 text-xs text-text-muted truncate">@{user.username}</div>
        </div>
        <div className="text-right shrink-0">
          <div className="inline-flex items-center gap-2 text-xs">
            <span className="text-accent font-semibold">{formatMoney(user.deposit)}</span>
            <span className="inline-flex items-center gap-1 text-accent">
              <Star className="size-3" />
              {user.reviews_count ? user.rating.toFixed(1) : "0.0"}
            </span>
          </div>
          <div className="mt-1 text-[11px] text-text-muted">{dealsLabel(user.deals_count)}</div>
        </div>
      </Link>
    </motion.div>
  );
}
