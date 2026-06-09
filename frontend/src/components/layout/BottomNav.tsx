import { Bell, Briefcase, Headphones, Search, User } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/cn";
import { parseNonNegativeIntegerValue } from "@/lib/format";
import { haptic } from "@/lib/tg";
import { useNotificationCounters } from "@/api/hooks";

const TABS = [
  { to: "/search", label: "Поиск", Icon: Search },
  { to: "/deals", label: "Сделки", Icon: Briefcase },
  { to: "/support", label: "Помощь", Icon: Headphones },
  { to: "/notifications", label: "Оповещения", Icon: Bell, badge: true },
  { to: "/profile", label: "Профиль", Icon: User },
];

/**
 * Continental `_navbar_1kzf0_1`:
 *   fixed bottom, full width, max-width 500px on desktop,
 *   grid 5 cols, flat bg-dark, no pill animation, icon above label,
 *   accent yellow for the active tab.
 */
export function BottomNav() {
  const location = useLocation();
  const activeRoot = TABS.find(
    (tab) => location.pathname === tab.to || location.pathname.startsWith(`${tab.to}/`),
  )?.to;
  const { data: counters } = useNotificationCounters();
  const unread = parseNonNegativeIntegerValue(counters?.unread) ?? 0;

  return (
    <nav
      className={cn(
        "fixed bottom-0 left-0 right-0 z-40",
        "mx-auto max-w-app",
        "h-navbar bg-panel shadow-navbar",
        "grid grid-cols-5 items-center justify-items-center",
        "px-3 pt-3",
      )}
      style={{ paddingBottom: "max(env(safe-area-inset-bottom, 0px), 12px)" }}
    >
      {TABS.map(({ to, label, Icon, badge }) => {
        const active = activeRoot === to;
        return (
          <NavLink
            key={to}
            to={to}
            onClick={() => haptic("light")}
            className={cn(
              "flex flex-col items-center gap-1 text-center text-[12px] leading-[14px]",
              active ? "text-accent" : "text-text-muted",
            )}
          >
            <span className="relative">
              <Icon className="size-6" strokeWidth={2} />
              {badge && unread > 0 && (
                <span
                  className={cn(
                    "absolute -top-1 -right-1.5 min-w-[16px] h-4 px-1 rounded-full",
                    "bg-danger text-white text-[10px] font-bold flex items-center justify-center",
                  )}
                >
                  {unread > 99 ? "99+" : unread}
                </span>
              )}
            </span>
            <span>{label}</span>
          </NavLink>
        );
      })}
    </nav>
  );
}
