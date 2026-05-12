import { NavLink, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { selectionChanged } from "@/telegram";

const items = [
  { to: "/", label: "Главная", icon: HomeIcon },
  { to: "/deals", label: "Сделки", icon: BriefcaseIcon },
  { to: "/balance", label: "Баланс", icon: DollarIcon },
  { to: "/profile", label: "Профиль", icon: UserIcon },
];

export default function BottomNav() {
  const { pathname } = useLocation();
  // Hide nav on the deal detail / create / admin screens to keep them focused.
  const hide =
    /^\/deals\/(new|\d+)/.test(pathname) || pathname.startsWith("/admin/");
  if (hide) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-30 pb-[env(safe-area-inset-bottom,0)]">
      <div className="mx-auto max-w-md px-3 pb-2">
        <div className="glass-card flex justify-between gap-1 px-2 py-2">
          {items.map(({ to, label, icon: Icon }) => (
            <NavLink
              to={to}
              end={to === "/"}
              key={to}
              onClick={() => selectionChanged()}
              className="relative flex-1"
            >
              {({ isActive }) => (
                <div className="relative flex flex-col items-center justify-center py-2 text-xs">
                  {isActive && (
                    <motion.div
                      layoutId="nav-pill"
                      className="absolute inset-0 rounded-2xl bg-gradient-to-br from-brand-300 to-brand-500"
                      transition={{ type: "spring", stiffness: 380, damping: 32 }}
                    />
                  )}
                  <Icon
                    className={`relative z-10 h-5 w-5 transition ${
                      isActive ? "text-bg" : "text-white/70"
                    }`}
                  />
                  <span
                    className={`relative z-10 mt-0.5 font-medium ${
                      isActive ? "text-bg" : "text-white/70"
                    }`}
                  >
                    {label}
                  </span>
                </div>
              )}
            </NavLink>
          ))}
        </div>
      </div>
    </div>
  );
}

function HomeIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <path d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" strokeLinejoin="round" />
    </svg>
  );
}
function BriefcaseIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
      <path d="M3 12h18" />
    </svg>
  );
}
function DollarIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <path d="M12 2v20" />
      <path d="M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  );
}
function UserIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" {...props}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
    </svg>
  );
}
