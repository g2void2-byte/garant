import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";

import { api } from "@/api";
import { Avatar, GradientText, Money } from "@/components/ui";
import { useUser } from "@/store";
import { haptic, notify } from "@/telegram";

export default function Profile() {
  const { user, setUser } = useUser();
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings,
  });

  const lock = useMutation({
    mutationFn: api.lockInsurance,
    onSuccess: (u) => {
      notify("success");
      setUser(u);
    },
    onError: (e) => {
      notify("error");
      alert((e as Error).message);
    },
  });
  const unlock = useMutation({
    mutationFn: api.unlockInsurance,
    onSuccess: (u) => {
      notify("success");
      setUser(u);
    },
  });

  if (!user) return null;
  const successRate = user.deals_total
    ? Math.round((user.deals_success / user.deals_total) * 100)
    : 100;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col gap-4 px-4 pt-6 pb-2"
    >
      <section className="glass-card relative overflow-hidden p-6">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_30%_-10%,rgba(255,167,36,0.35),transparent_45%),radial-gradient(circle_at_80%_120%,rgba(160,80,255,0.3),transparent_45%)]" />
        <div className="relative flex flex-col items-center text-center">
          <div className="rounded-full bg-bg/70 px-3 py-1 text-xs text-white/70 backdrop-blur">
            {user.username ? `@${user.username}` : `id ${user.tg_id}`}
          </div>
          <div className="relative my-4 inline-flex items-center justify-center">
            <div className="absolute -inset-3 rounded-3xl bg-gradient-to-br from-brand/40 via-fuchsia-500/30 to-indigo-500/40 blur-xl animate-glow" />
            <div className="relative rounded-3xl bg-bg/60 p-3 ring-1 ring-white/10">
              <Avatar
                url={user.photo_url}
                name={`${user.first_name ?? ""} ${user.last_name ?? ""}`}
                size={96}
                className="!rounded-2xl"
              />
            </div>
          </div>
          <h1 className="text-2xl font-bold">
            <GradientText>
              {user.first_name ?? "Пользователь"} {user.last_name ?? ""}
            </GradientText>
          </h1>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3">
        <BigStat label="Баланс" value={<Money value={user.balance} />} />
        <BigStat label="Страх. депозит" value={<Money value={user.insurance} />} />
        <BigStat label="Заморожено" value={<Money value={user.frozen} />} />
        <BigStat label="Рейтинг" value={user.rating.toFixed(1)} />
      </section>

      <section className="glass-card grid grid-cols-2 gap-3 p-4">
        <Mini
          label="Успешных сделок"
          value={`${user.deals_success} / ${user.deals_total}`}
          icon="📈"
        />
        <Mini label="Успех" value={`${successRate}%`} icon="🛡" />
      </section>

      <section className="glass-card flex flex-col gap-3 p-5">
        <h2 className="text-lg font-semibold">Страховой депозит</h2>
        <p className="text-sm text-white/55">
          Продавцу необходимо внести страховой депозит до создания сделки.
          Депозит возвращается на баланс при отключении.
          {settings && (
            <>
              {" "}Требуется:{" "}
              <span className="font-semibold text-white">
                <Money value={settings.insurance_deposit} />
              </span>
            </>
          )}
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => {
              haptic("medium");
              lock.mutate();
            }}
            disabled={lock.isPending}
            className="btn-primary flex-1"
          >
            🛡 Внести
          </button>
          <button
            onClick={() => unlock.mutate()}
            disabled={unlock.isPending || user.insurance <= 0}
            className="btn-ghost flex-1 disabled:opacity-50"
          >
            ↩ Вернуть
          </button>
        </div>
      </section>

      {user.is_admin && (
        <Link
          to="/admin"
          className="glass-card flex items-center justify-between p-5 transition hover:border-brand/30"
        >
          <div>
            <div className="text-base font-semibold">⚙ Админ-панель</div>
            <div className="text-xs text-white/55">
              Пользователи, сделки, споры, настройки
            </div>
          </div>
          <div className="pill bg-brand/15 text-brand-300">Открыть →</div>
        </Link>
      )}
    </motion.div>
  );
}

function BigStat({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="glass-card p-4">
      <div className="text-2xl font-extrabold">{value}</div>
      <div className="mt-1 text-xs uppercase tracking-wide text-white/50">
        {label}
      </div>
    </div>
  );
}

function Mini({
  label,
  value,
  icon,
}: {
  label: string;
  value: React.ReactNode;
  icon: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-2xl bg-bg/40 p-3">
      <div className="rounded-xl bg-brand/15 p-2 text-lg">{icon}</div>
      <div>
        <div className="text-sm font-semibold">{value}</div>
        <div className="text-xs text-white/50">{label}</div>
      </div>
    </div>
  );
}
