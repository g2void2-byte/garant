import { motion } from "framer-motion";
import { Bell, Briefcase, Headphones, Search, User } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/cn";
import { haptic } from "@/lib/tg";
import { useNotificationCounters } from "@/api/hooks";

const TABS = [
  { to: "/search", label: "Поиск", Icon: Search, badgeKey: null },
  { to: "/deals", label: "Сделки", Icon: Briefcase, badgeKey: null },
  { to: "/help", label: "Помощь", Icon: Headphones, badgeKey: null },
  { to: "/notifications", label: "Оповещения", Icon: Bell, badgeKey: "unread" as const },
  { to: "/profile", label: "Профиль", Icon: User, badgeKey: null },
];

export function BottomNav() {
  const location = useLocation();
  const activeRoot = TABS.find((tab) => location.pathname === tab.to || location.pathname.startsWith(`${tab.to}/`))?.to;
  const { data: counters } = useNotificationCounters();
  return (
    <nav
      className={cn(
        "fixed bottom-0 left-0 right-0 z-40 px-3 pb-3 safe-bottom",
        "before:absolute before:inset-x-0 before:top-0 before:h-6 before:-translate-y-full",
        "before:bg-gradient-to-t before:from-bg before:to-transparent before:pointer-events-none",
      )}
    >
      <div className="mx-auto max-w-[460px] rounded-3xl border border-border bg-panel shadow-pop">
        <ul className="grid grid-cols-5 gap-1 p-1.5">
          {TABS.map(({ to, label, Icon, badgeKey }) => {
            const active = activeRoot === to;
            const badge = badgeKey && counters ? counters[badgeKey] : 0;
            return (
              <li key={to}>
                <NavLink
                  to={to}
                  onClick={() => haptic("light")}
                  className={cn(
                    "relative flex flex-col items-center justify-center py-2 rounded-2xl text-[11px] font-medium",
                    active ? "text-accent-fg" : "text-text-muted",
                  )}
                >
                  {active && (
                    <motion.span
                      layoutId="nav-pill"
                      className="absolute inset-0 rounded-2xl bg-accent"
                      transition={{ type: "spring", stiffness: 500, damping: 32 }}
                    />
                  )}
                  <span className="relative z-10 flex flex-col items-center gap-1">
                    <span className="relative">
                      <Icon className="size-5" />
                      {badge > 0 && (
                        <motion.span
                          key={badge}
                          initial={{ scale: 0.6, opacity: 0 }}
                          animate={{ scale: 1, opacity: 1 }}
                          transition={{ type: "spring", stiffness: 500, damping: 24 }}
                          className={cn(
                            "absolute -top-1.5 -right-2 min-w-[16px] h-[16px] px-1 grid place-items-center",
                            "rounded-full text-[10px] font-bold leading-none",
                            active ? "bg-accent-fg text-accent" : "bg-accent text-accent-fg",
                          )}
                          aria-label={`${badge} непрочитанных`}
                        >
                          {badge > 99 ? "99+" : badge}
                        </motion.span>
                      )}
                    </span>
                    <span>{label}</span>
                  </span>
                </NavLink>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}
