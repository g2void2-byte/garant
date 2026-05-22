import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowUpFromLine,
  Bell,
  Briefcase,
  Coins,
  Gavel,
  History,
  LayoutDashboard,
  LineChart,
  Server,
  Settings as SettingsIcon,
  ShieldCheck,
  Tags,
  Users,
  Vault,
  X,
} from "lucide-react";
import { staggerDelay } from "@/lib/animate";
import { cn } from "@/lib/cn";

/**
 * Slide-in admin menu drawer.
 *
 * The drawer slides in from the left (translate-x-(-100%) →
 * translate-x-0) with a backdrop behind it. Items appear one-by-one
 * via a staggered ``animate-fade-in-up`` so the panel feels
 * responsive even on slow Telegram WebView devices.
 *
 * Visibility is controlled by ``useUI.adminMenuOpen`` so a Menu
 * button rendered in the header of *any* /admin/* page can toggle
 * the drawer regardless of which page mounted it. The component
 * itself is mounted once globally (in ``App.tsx``) — page bodies
 * just dispatch the open state.
 */
export interface AdminMenuItem {
  to: string;
  label: string;
  icon: React.ReactNode;
}

const ITEMS: AdminMenuItem[] = [
  { to: "/admin/dashboard", label: "Дашборд", icon: <LayoutDashboard size={18} /> },
  { to: "/admin/users", label: "Пользователи", icon: <Users size={18} /> },
  { to: "/admin/deals", label: "Сделки", icon: <Briefcase size={18} /> },
  { to: "/admin/arbitration", label: "Арбитраж", icon: <Gavel size={18} /> },
  { to: "/admin/wallets", label: "Кошельки", icon: <Vault size={18} /> },
  { to: "/admin/deposits", label: "Депозиты", icon: <ArrowDownToLine size={18} /> },
  { to: "/admin/withdrawals", label: "Выводы", icon: <ArrowUpFromLine size={18} /> },
  { to: "/admin/treasury", label: "Treasury", icon: <Vault size={18} /> },
  { to: "/admin/broadcasts", label: "Рассылки", icon: <Bell size={18} /> },
  { to: "/admin/analytics", label: "Аналитика", icon: <LineChart size={18} /> },
  { to: "/admin/taxonomy", label: "Таксономия", icon: <Tags size={18} /> },
  { to: "/admin/taxonomy", label: "Валюты", icon: <Coins size={18} /> },
  { to: "/admin/settings", label: "Настройки", icon: <SettingsIcon size={18} /> },
  { to: "/admin/system", label: "Система", icon: <Server size={18} /> },
  { to: "/admin/audit", label: "Аудит", icon: <History size={18} /> },
  { to: "/admin/2fa", label: "2FA", icon: <ShieldCheck size={18} /> },
];

interface AdminMenuProps {
  open: boolean;
  onClose: () => void;
}

export function AdminMenu({ open, onClose }: AdminMenuProps) {
  const navigate = useNavigate();
  const location = useLocation();

  // Lock body scroll while the drawer is open so the backdrop blur
  // reads cleanly on iOS Telegram. The cleanup restores the
  // original overflow rather than blindly setting ``""`` because
  // other modals on the page may already have locked it.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // ESC closes the drawer — standard a11y affordance and matches
  // Telegram's native modal patterns.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      {/* Backdrop with a fade-in. ``pointer-events-none`` on the
          closed state lets clicks pass through to the page below
          so the drawer doesn't accidentally swallow taps when
          collapsed. */}
      <div
        aria-hidden
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-200 ease-out",
          open ? "opacity-100" : "opacity-0 pointer-events-none",
        )}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Меню админки"
        data-testid="admin-menu"
        className={cn(
          "fixed left-0 top-0 z-50 h-full w-[78vw] max-w-[360px] bg-panel shadow-2xl",
          "transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <header className="safe-top flex items-center justify-between px-4 pt-4 pb-3">
          <h2 className="text-lg font-semibold">Меню</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть меню"
            className="rounded-button p-2 -m-2 text-text-muted hover:text-text transition"
          >
            <X size={20} />
          </button>
        </header>
        <nav className="px-3 py-1 space-y-1 overflow-y-auto h-[calc(100%-64px)]">
          {ITEMS.map((item, i) => {
            const active = location.pathname.startsWith(item.to);
            return (
              <button
                key={`${item.to}-${item.label}`}
                type="button"
                onClick={() => {
                  navigate(item.to);
                  onClose();
                }}
                style={open ? staggerDelay(i, 35, 280) : undefined}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-card text-left transition active:scale-[0.98]",
                  open && "animate-fade-in-up",
                  active
                    ? "bg-accent/10 text-accent"
                    : "text-text hover:bg-panel-2",
                )}
              >
                <span className={active ? "text-accent" : "text-text-muted"}>
                  {item.icon}
                </span>
                <span className="text-sm font-medium">{item.label}</span>
                {item.label === "Арбитраж" && (
                  <AlertTriangle
                    size={14}
                    className="ml-auto text-amber-400/80"
                    aria-hidden
                  />
                )}
              </button>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
