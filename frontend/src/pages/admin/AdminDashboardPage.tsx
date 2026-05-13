import { useNavigate } from "react-router-dom";
import { ShieldCheck, Users, Briefcase, AlertTriangle, Gavel, Crown } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAdminDashboard } from "@/api/admin/hooks";
import { useMe } from "@/api/hooks";

/**
 * Continental admin home page.
 *
 * Shows KPI counters fetched from `/api/admin/dashboard`. Refreshes
 * every 30s so the operator sees fresh numbers while triaging.
 */
export default function AdminDashboardPage() {
  const navigate = useNavigate();
  const { data: me } = useMe();
  const { data, isLoading, error } = useAdminDashboard();

  // Defence-in-depth: server returns 403 too, but redirect early so the
  // page never flashes its scaffolding to a non-admin.
  if (me && !me.is_admin) {
    navigate("/search", { replace: true });
    return null;
  }

  return (
    <Page showBack onBack={() => navigate("/profile")}>
      <Header title="Админ-панель" subtitle="Управление платформой" />

      {isLoading ? (
        <DashboardSkeleton />
      ) : error ? (
        <div className="px-4 py-3 text-sm text-red-400">
          Не удалось загрузить статистику
        </div>
      ) : data ? (
        <div className="px-4 space-y-4">
          <Section title="Пользователи">
            <Tile
              icon={<Users size={18} />}
              label="Всего"
              value={data.total_users}
              onClick={() => navigate("/admin/users")}
            />
            <Tile
              icon={<Users size={18} />}
              label="Новые за 24ч"
              value={data.new_users_24h}
            />
            <Tile
              icon={<Users size={18} />}
              label="Новые за 7 дн."
              value={data.new_users_7d}
            />
            <Tile
              icon={<Users size={18} />}
              label="Онлайн (5 мин)"
              value={data.online_users_5min}
            />
          </Section>

          <Section title="Сделки">
            <Tile
              icon={<Briefcase size={18} />}
              label="Всего"
              value={data.total_deals}
              onClick={() => navigate("/admin/deals")}
            />
            <Tile
              icon={<Briefcase size={18} />}
              label="Открытые"
              value={data.open_deals}
              onClick={() => navigate("/admin/deals?status=in_progress")}
            />
            <Tile
              icon={<Gavel size={18} />}
              label="В арбитраже"
              value={data.open_arbitration}
              accent={data.open_arbitration > 0}
              onClick={() => navigate("/admin/arbitration")}
            />
          </Section>

          <Section title="Услуги">
            <Tile
              icon={<Briefcase size={18} />}
              label="Всего"
              value={data.total_services}
            />
            <Tile
              icon={<Briefcase size={18} />}
              label="Активные"
              value={data.active_services}
            />
          </Section>

          <Section title="Модерация">
            <Tile
              icon={<AlertTriangle size={18} />}
              label="Забаненные"
              value={data.banned_users}
              accent={data.banned_users > 0}
              onClick={() =>
                navigate("/admin/users?status=banned")
              }
            />
            <Tile
              icon={<AlertTriangle size={18} />}
              label="Заморожены"
              value={data.frozen_users}
              onClick={() => navigate("/admin/users?status=frozen")}
            />
          </Section>

          <Section title="Роли">
            <Tile
              icon={<ShieldCheck size={18} />}
              label="Админы"
              value={data.admins}
              onClick={() => navigate("/admin/users?role=admin")}
            />
            <Tile
              icon={<Gavel size={18} />}
              label="Арбитры"
              value={data.arbiters}
              onClick={() => navigate("/admin/users?role=arbiter")}
            />
            <Tile
              icon={<Crown size={18} />}
              label="VIP"
              value={data.vips}
              onClick={() => navigate("/admin/users?role=vip")}
            />
          </Section>
        </div>
      ) : null}
    </Page>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
        {title}
      </h2>
      <div className="grid grid-cols-2 gap-2">{children}</div>
    </section>
  );
}

function Tile({
  icon,
  label,
  value,
  onClick,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  onClick?: () => void;
  accent?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick}
      className={`flex flex-col items-start gap-1 rounded-lg p-3 bg-panel text-left transition active:scale-[0.98] ${
        onClick ? "hover:bg-panel-2" : ""
      } ${accent ? "ring-1 ring-accent" : ""}`}
    >
      <span className="text-text-muted">{icon}</span>
      <span className="text-2xl font-bold tabular-nums">{value}</span>
      <span className="text-xs text-text-muted">{label}</span>
    </button>
  );
}

function DashboardSkeleton() {
  return (
    <div className="px-4 space-y-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-3 w-24" />
          <div className="grid grid-cols-2 gap-2">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
        </div>
      ))}
    </div>
  );
}
