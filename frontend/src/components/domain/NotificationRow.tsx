import { Bell, Briefcase, Wallet, Check } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { NotificationDto } from "@/api/types";
import { cn } from "@/lib/cn";
import { relativeTime } from "@/lib/format";
import { staggerDelay, useHorizontalSwipe } from "@/lib/animate";
import { parsePositiveIntValue } from "@/lib/routeParams";

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
  const navigate = useNavigate();
  const notificationId = parsePositiveIntValue(item.id);
  const canOpen = notificationId !== undefined;
  const openNotification = () => {
    if (notificationId !== undefined) navigate(`/notifications/${notificationId}`);
  };
  const swipe = useHorizontalSwipe(() => {
    if (notificationId !== undefined) onRead?.(notificationId);
  });
  const Icon = ICONS[item.type] ?? Bell;

  return (
    <div
      className="relative overflow-hidden rounded-card animate-fadein"
      style={staggerDelay(index, 20, 200)}
    >
      <div className="absolute inset-0 flex items-center justify-end pr-4 rounded-card bg-success text-accent-fg">
        <Check className="size-5" />
      </div>
      <div
        ref={swipe.elRef}
        onPointerDown={item.is_read || !canOpen ? undefined : swipe.onPointerDown}
        onPointerMove={item.is_read || !canOpen ? undefined : swipe.onPointerMove}
        onPointerUp={item.is_read || !canOpen ? undefined : swipe.onPointerUp}
        onClick={canOpen ? openNotification : undefined}
        role="button"
        aria-disabled={!canOpen}
        tabIndex={canOpen ? 0 : -1}
        onKeyDown={(e) => {
          if (!canOpen) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            openNotification();
          }
        }}
        className={cn(
          "relative flex items-start gap-3 p-3 rounded-card border bg-panel touch-none",
          item.is_read ? "border-border" : "border-accent/40",
          canOpen ? "cursor-pointer" : "cursor-not-allowed opacity-60",
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
      </div>
    </div>
  );
}
