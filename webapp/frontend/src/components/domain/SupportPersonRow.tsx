import { motion } from "framer-motion";
import { ExternalLink } from "lucide-react";
import type { SupportPersonDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { openTelegramLink } from "@/lib/tg";

export function SupportPersonRow({ person, index = 0 }: { person: SupportPersonDto; index?: number }) {
  return (
    <motion.button
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.04, 0.3), duration: 0.2 }}
      whileTap={{ scale: 0.98 }}
      onClick={() => openTelegramLink(`https://t.me/${person.username}`)}
      className="w-full flex items-center gap-3 bg-panel border border-border rounded-card p-3 text-left"
    >
      <Avatar name={person.username} size={44} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <BadgePrefix prefix={person.prefix} />
          <span className="font-semibold truncate">@{person.username}</span>
        </div>
        <div className="mt-1 text-xs text-text-muted">{person.prefix === "admin" ? "Администратор" : "Арбитр"}</div>
      </div>
      <ExternalLink className="size-4 text-text-muted" />
    </motion.button>
  );
}
