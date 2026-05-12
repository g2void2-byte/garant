import { motion, useMotionValue, useTransform } from "framer-motion";
import { Bell, Briefcase, Wallet, Check } from "lucide-react";
import type { NotificationDto } from "@/api/types";
import { cn } from "@/lib/cn";
import { relativeTime } from "@/lib/format";

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  deals: Briefcase,
  deposits: Wallet,
  system: Bell,
};

interface Props {
  item: NotificationDto;
  index?: number;
  onRead?: (id: number) => void;
}

export function NotificationRow({ item, index = 0, onRead }: Props) {
  const x = useMotionValue(0);
  const bg = useTransform(x, [-80, 0], ["var(--success)", "transparent"]);
  const Icon = ICONS[item.type] ?? Bell;

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.02, 0.2), duration: 0.18 }}
      className="relative overflow-hidden rounded-card"
    >
      <motion.div
        style={{ background: bg }}
        className="absolute inset-0 flex items-center justify-end pr-4 rounded-card text-accent-fg"
      >
        <Check className="size-5" />
      </motion.div>
      <motion.div
        drag={item.is_read ? false : "x"}
        dragConstraints={{ left: -80, right: 0 }}
        dragElastic={0.2}
        onDragEnd={(_, info) => {
          if (info.offset.x < -50) onRead?.(item.id);
        }}
        style={{ x }}
        className={cn(
          "relative flex items-start gap-3 p-3 rounded-card border bg-panel",
          item.is_read ? "border-border" : "border-accent/40",
        )}
      >
        <div
          className={cn(
            "size-10 grid place-items-center rounded-full shrink-0",
            item.is_read ? "bg-panel-2 text-text-muted" : "bg-accent/15 text-accent",
          )}
        >
          <Icon className="size-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold truncate">{item.title}</span>
            {!item.is_read && <span className="size-2 rounded-full bg-accent shrink-0" />}
          </div>
          {item.body && <div className="mt-1 text-sm text-text-muted line-clamp-2">{item.body}</div>}
          <div className="mt-1 text-[11px] text-text-muted">{relativeTime(item.created_at)}</div>
        </div>
      </motion.div>
    </motion.div>
  );
}
