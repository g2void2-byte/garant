import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";

import { useUser } from "@/store";

const tabs = [
  { to: "dashboard", label: "Обзор", icon: "📊" },
  { to: "users", label: "Пользователи", icon: "👥" },
  { to: "deals", label: "Сделки", icon: "💼" },
  { to: "settings", label: "Настройки", icon: "⚙" },
];

export default function AdminLayout() {
  const { user } = useUser();
  const navigate = useNavigate();
  if (!user) return null;
  if (!user.is_admin) {
    return (
      <div className="p-8 text-center">
        <div className="text-2xl">🚫</div>
        <p className="mt-2 text-white/60">У вас нет доступа к админ-панели</p>
        <button
          onClick={() => navigate("/")}
          className="btn-primary mt-4 inline-flex"
        >
          На главную
        </button>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-4 px-4 pt-6"
    >
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">
          ⚙ Админ-панель
        </h1>
        <button
          onClick={() => navigate("/")}
          className="text-sm text-white/55 hover:text-white"
        >
          Выйти →
        </button>
      </header>

      <nav className="-mx-2 flex gap-2 overflow-x-auto px-2">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `pill whitespace-nowrap ${
                isActive
                  ? "bg-brand text-bg shadow-glow"
                  : "bg-bg-card/60 text-white/70 hover:text-white"
              }`
            }
          >
            <span className="mr-1">{t.icon}</span>
            {t.label}
          </NavLink>
        ))}
      </nav>

      <div className="flex flex-col gap-4 pb-12">
        <Outlet />
      </div>
    </motion.div>
  );
}
