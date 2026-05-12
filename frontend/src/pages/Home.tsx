import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";

import type { UserShort } from "@/api";
import { api } from "@/api";
import { useUser } from "@/store";
import { Avatar, AnimatedNumber, GradientText } from "@/components/ui";
import { haptic, selectionChanged } from "@/telegram";

export default function Home({
  initialTab,
}: {
  initialTab?: "deals" | "search";
} = {}) {
  const { user } = useUser();
  const [tab, setTab] = useState<"deals" | "search">(initialTab ?? "deals");
  const [q, setQ] = useState("");
  const [results, setResults] = useState<UserShort[]>([]);
  const navigate = useNavigate();

  useEffect(() => {
    const id = setTimeout(() => {
      api.searchUsers(q).then(setResults).catch(() => {});
    }, 150);
    return () => clearTimeout(id);
  }, [q]);

  const stats = useMemo(() => {
    if (!user) return null;
    return [
      { label: "Баланс", value: user.balance, accent: true },
      { label: "В эскроу", value: user.frozen },
      { label: "Рейтинг", value: user.rating, suffix: " / 5", isRating: true },
      { label: "Сделки", value: user.deals_total, isInt: true },
    ];
  }, [user]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-6 px-4 pt-8"
    >
      <header className="text-center">
        <h1 className="text-3xl font-extrabold tracking-tight">
          <GradientText>AutoGarant</GradientText>
        </h1>
        <p className="mx-auto mt-1 max-w-xs text-sm text-white/55">
          Эскроу и страховой депозит для безопасных сделок
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3">
        <TabButton
          active={tab === "deals"}
          onClick={() => {
            setTab("deals");
            selectionChanged();
            navigate("/deals");
          }}
        >
          💼 Сделки
        </TabButton>
        <TabButton
          active={tab === "search"}
          onClick={() => {
            setTab("search");
            selectionChanged();
          }}
        >
          👥 Поиск
        </TabButton>
      </div>

      {tab === "search" && (
        <SearchCard q={q} setQ={setQ} results={results} />
      )}

      <section className="glass-card p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Статистика</h2>
          {user?.is_admin && (
            <Link
              to="/admin"
              className="pill bg-brand/15 text-brand-300 hover:bg-brand/25"
            >
              ⚙ Админка
            </Link>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3">
          {stats?.map((s) => (
            <div key={s.label} className="rounded-2xl bg-bg/40 p-4">
              <div className="text-xs uppercase tracking-wide text-white/45">
                {s.label}
              </div>
              <div
                className={`mt-1 text-2xl font-bold ${s.accent ? "text-brand" : ""}`}
              >
                {s.isInt ? (
                  s.value
                ) : s.isRating ? (
                  <>
                    {s.value.toFixed(1)}
                    <span className="text-base text-white/40">{s.suffix}</span>
                  </>
                ) : (
                  <AnimatedNumber value={s.value} />
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="glass-card p-5">
        <h2 className="mb-3 text-lg font-semibold">Быстрые действия</h2>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/deals/new"
            onClick={() => haptic("medium")}
            className="btn-primary"
          >
            ➕ Создать сделку
          </Link>
          <Link to="/balance" className="btn-ghost">
            💰 Пополнить
          </Link>
          <Link to="/profile" className="btn-ghost">
            🛡 Депозит
          </Link>
        </div>
      </section>
    </motion.div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`relative overflow-hidden rounded-full py-3 text-sm font-semibold transition ${
        active
          ? "bg-gradient-to-br from-brand-200 via-brand-400 to-brand-500 text-bg shadow-glow"
          : "bg-bg-card/60 text-white/70 hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}

function SearchCard({
  q,
  setQ,
  results,
}: {
  q: string;
  setQ: (s: string) => void;
  results: UserShort[];
}) {
  return (
    <section className="glass-card p-5">
      <div className="mb-3 flex items-center gap-2">
        <div className="rounded-xl bg-brand/15 p-2 text-brand">👥</div>
        <h2 className="text-lg font-semibold">Поиск участников</h2>
      </div>
      <p className="mb-3 text-xs text-white/50">
        Введите @username, имя или начало Telegram ID — показываются
        пользователи, которые уже заходили в приложение.
      </p>
      <input
        autoFocus
        value={q}
        onChange={(e) => setQ(e.target.value)}
        className="input"
        placeholder="@username, имя или ID"
      />
      <div className="mt-3 space-y-2">
        {results.slice(0, 10).map((u) => (
          <Link
            to={`/deals/new?counterparty=${u.tg_id}`}
            key={u.id}
            onClick={() => selectionChanged()}
            className="flex items-center gap-3 rounded-2xl bg-bg/40 p-3 hover:bg-bg/60"
          >
            <Avatar
              url={u.photo_url}
              name={`${u.first_name ?? ""} ${u.last_name ?? ""}`}
            />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">
                {u.first_name ?? "—"} {u.last_name ?? ""}
              </div>
              <div className="truncate text-xs text-white/50">
                {u.username ? `@${u.username}` : `id ${u.tg_id}`} · ★ {u.rating.toFixed(1)}
              </div>
            </div>
            <span className="pill bg-brand/15 text-brand-300">Сделка →</span>
          </Link>
        ))}
        {results.length === 0 && (
          <div className="rounded-2xl bg-bg/30 p-4 text-center text-sm text-white/40">
            Никого не нашли
          </div>
        )}
      </div>
    </section>
  );
}
