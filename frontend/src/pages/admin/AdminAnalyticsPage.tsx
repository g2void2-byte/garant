import { useNavigate } from "react-router-dom";
import { Activity, Users, TrendingUp, Wallet } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  useAdminAnalyticsKpi,
  useAdminAnalyticsSeries,
  useAdminAnalyticsTop,
} from "@/api/admin/hooks";
import type { AdminAnalyticsSeriesPointDto } from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

/**
 * `/admin/analytics` — KPI cards, 30-day sparklines, top-user lists.
 *
 * Backend returns plain points; we sparkline them inline with pure SVG
 * so we don't take a charting dep just for the admin panel. Auto-
 * refresh every minute.
 */
export default function AdminAnalyticsPage() {
  const navigate = useNavigate();
  const kpi = useAdminAnalyticsKpi();
  const series = useAdminAnalyticsSeries();
  const top = useAdminAnalyticsTop();

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader title="Аналитика" subtitle="30 дней" />
      <div className="px-4 grid grid-cols-2 gap-2 mb-4">
        <KpiCard
          icon={<Users size={14} />}
          label="DAU / WAU / MAU"
          value={
            kpi.data ? `${kpi.data.dau} / ${kpi.data.wau} / ${kpi.data.mau}` : "—"
          }
          loading={kpi.isLoading}
        />
        <KpiCard
          icon={<Activity size={14} />}
          label="Новых юзеров (24h / 7d)"
          value={
            kpi.data ? `${kpi.data.new_users_24h} / ${kpi.data.new_users_7d}` : "—"
          }
          loading={kpi.isLoading}
        />
        <KpiCard
          icon={<TrendingUp size={14} />}
          label="Сделок (24h / 7d)"
          value={kpi.data ? `${kpi.data.deals_24h} / ${kpi.data.deals_7d}` : "—"}
          loading={kpi.isLoading}
        />
        <KpiCard
          icon={<Wallet size={14} />}
          label="Объём (30d)"
          value={
            kpi.data
              ? `$${kpi.data.deals_volume_usd_30d.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
              : "—"
          }
          loading={kpi.isLoading}
        />
        <KpiCard
          label="Открытых арбитражей"
          value={kpi.data ? String(kpi.data.open_arbitration) : "—"}
          loading={kpi.isLoading}
          accent="warning"
        />
        <KpiCard
          label="Ожидают вывод"
          value={kpi.data ? String(kpi.data.pending_withdrawals) : "—"}
          loading={kpi.isLoading}
          accent="warning"
        />
      </div>

      <div className="px-4 space-y-3">
        {series.isLoading ? (
          Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-card" />
          ))
        ) : (
          <>
            <SparklineCard
              title="Сделки в день"
              data={series.data?.deals_count_30d ?? []}
            />
            <SparklineCard
              title="Объём ($) в день"
              data={series.data?.deals_volume_30d ?? []}
              format={(v) => `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
            />
            <SparklineCard
              title="Новые юзеры в день"
              data={series.data?.new_users_30d ?? []}
            />
            <SparklineCard
              title="Депозиты в день"
              data={series.data?.deposits_30d ?? []}
            />
            <SparklineCard
              title="Выводы в день"
              data={series.data?.withdrawals_30d ?? []}
            />
          </>
        )}
      </div>

      <div className="px-4 mt-4 pb-24 space-y-3">
        <TopList title="Топ продавцов" entries={top.data?.top_sellers ?? []} />
        <TopList title="Топ покупателей" entries={top.data?.top_buyers ?? []} />
        <TopList title="Топ арбитров" entries={top.data?.top_arbiters ?? []} />
      </div>
    </Page>
  );
}

function KpiCard({
  icon,
  label,
  value,
  loading,
  accent,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
  loading?: boolean;
  accent?: "warning" | "danger" | "success";
}) {
  if (loading) return <Skeleton className="h-16 rounded-card" />;
  return (
    <div
      className={`bg-panel rounded-card p-3 ${
        accent === "warning" ? "ring-1 ring-warning/40" : ""
      }`}
    >
      <div className="flex items-center gap-1 text-xs text-text-muted mb-1">
        {icon}
        {label}
      </div>
      <div className="text-lg font-bold">{value}</div>
    </div>
  );
}

function SparklineCard({
  title,
  data,
  format,
}: {
  title: string;
  data: AdminAnalyticsSeriesPointDto[];
  format?: (v: number) => string;
}) {
  if (data.length === 0) {
    return (
      <div className="bg-panel rounded-card p-3">
        <div className="text-xs text-text-muted">{title}</div>
        <div className="text-sm text-text-muted mt-2">Нет данных</div>
      </div>
    );
  }
  const max = Math.max(...data.map((d) => d.value), 1);
  const points = data
    .map((d, i) => {
      const x = (i / Math.max(data.length - 1, 1)) * 100;
      const y = 100 - (d.value / max) * 100;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = data[data.length - 1]?.value ?? 0;
  return (
    <div
      className="bg-panel rounded-card p-3"
    >
      <div className="flex items-baseline justify-between">
        <div className="text-xs text-text-muted">{title}</div>
        <div className="text-sm font-semibold">
          {format ? format(last) : last}
        </div>
      </div>
      <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="w-full h-12 mt-2">
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="1.2"
          points={points
            .split(" ")
            .map((p) => {
              const [x, y] = p.split(",").map(Number);
              return `${x},${(y / 100) * 28}`;
            })
            .join(" ")}
          className="text-accent"
        />
      </svg>
    </div>
  );
}

function TopList({
  title,
  entries,
}: {
  title: string;
  entries: Array<{
    user_id: number;
    username: string | null;
    display_name: string;
    value: number;
  }>;
}) {
  return (
    <div className="bg-panel rounded-card p-3">
      <div className="text-xs text-text-muted mb-2">{title}</div>
      {entries.length === 0 ? (
        <div className="text-sm text-text-muted">Нет данных</div>
      ) : (
        <div className="space-y-1.5">
          {entries.map((e, i) => (
            <div key={e.user_id} className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-text-muted w-5 text-right">{i + 1}.</span>
                <span className="truncate">
                  {e.display_name}{" "}
                  <span className="text-text-muted">@{e.username ?? "—"}</span>
                </span>
              </div>
              <span className="font-mono text-text-muted">{e.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
