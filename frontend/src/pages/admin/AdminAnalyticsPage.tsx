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
import { formatCountValue, parseDecimalValue, parseNonNegativeIntegerValue } from "@/lib/format";
import { formatAdminUsername } from "./format";

/**
 * `/admin/analytics` — KPI cards, 30-day sparklines, top-user lists.
 *
 * Backend returns plain points; we sparkline them inline with pure SVG
 * so we don't take a charting dep just for the admin panel. Auto-
 * refresh every minute.
 */
const DASH = "\u2014";

function parseNonNegativeDecimalValue(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  const parsed = parseDecimalValue(value);
  return parsed !== null && parsed >= 0 ? parsed : null;
}

function formatCountTuple(values: unknown[]): string {
  return values.map((value) => formatCountValue(value)).join(" / ");
}

function formatAnalyticsUsd(value: unknown): string {
  const parsed = parseNonNegativeDecimalValue(value);
  return parsed === null
    ? DASH
    : `$${parsed.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function formatAnalyticsNumber(value: unknown): string {
  const parsed = parseNonNegativeDecimalValue(value);
  return parsed === null
    ? DASH
    : parsed.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

type SeriesValueKind = "count" | "decimal";

function parseSeriesValue(value: unknown, kind: SeriesValueKind): number | null {
  if (kind === "count") return parseNonNegativeIntegerValue(value);
  return parseNonNegativeDecimalValue(value);
}

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
            kpi.data ? formatCountTuple([kpi.data.dau, kpi.data.wau, kpi.data.mau]) : "—"
          }
          loading={kpi.isLoading}
        />
        <KpiCard
          icon={<Activity size={14} />}
          label="Новых юзеров (24h / 7d)"
          value={
            kpi.data ? formatCountTuple([kpi.data.new_users_24h, kpi.data.new_users_7d]) : "—"
          }
          loading={kpi.isLoading}
        />
        <KpiCard
          icon={<TrendingUp size={14} />}
          label="Сделок (24h / 7d)"
          value={kpi.data ? formatCountTuple([kpi.data.deals_24h, kpi.data.deals_7d]) : "—"}
          loading={kpi.isLoading}
        />
        <KpiCard
          icon={<Wallet size={14} />}
          label="Объём (30d)"
          value={kpi.data ? formatAnalyticsUsd(kpi.data.deals_volume_usd_30d) : "—"}
          loading={kpi.isLoading}
        />
        <KpiCard
          label="Открытых арбитражей"
          value={kpi.data ? formatCountValue(kpi.data.open_arbitration) : "—"}
          loading={kpi.isLoading}
          accent="warning"
        />
        <KpiCard
          label="Ожидают вывод"
          value={kpi.data ? formatCountValue(kpi.data.pending_withdrawals) : "—"}
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
              valueKind="decimal"
              format={formatAnalyticsUsd}
            />
            <SparklineCard
              title="Новые юзеры в день"
              data={series.data?.new_users_30d ?? []}
            />
            <SparklineCard
              title="Депозиты в день"
              data={series.data?.deposits_30d ?? []}
              valueKind="decimal"
            />
            <SparklineCard
              title="Выводы в день"
              data={series.data?.withdrawals_30d ?? []}
              valueKind="decimal"
            />
          </>
        )}
      </div>

      <div className="px-4 mt-4 pb-24 space-y-3">
        <TopList title="Топ продавцов" entries={top.data?.top_sellers ?? []} valueKind="decimal" />
        <TopList title="Топ покупателей" entries={top.data?.top_buyers ?? []} valueKind="decimal" />
        <TopList title="Топ арбитров" entries={top.data?.top_arbiters ?? []} valueKind="count" />
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
  valueKind = "count",
}: {
  title: string;
  data: AdminAnalyticsSeriesPointDto[];
  format?: (v: number) => string;
  valueKind?: SeriesValueKind;
}) {
  const values = data
    .map((d) => parseSeriesValue(d.value, valueKind))
    .filter((value): value is number => value !== null);
  if (values.length === 0) {
    return (
      <div className="bg-panel rounded-card p-3">
        <div className="text-xs text-text-muted">{title}</div>
        <div className="text-sm text-text-muted mt-2">Нет данных</div>
      </div>
    );
  }
  const max = Math.max(...values, 1);
  const points = values
    .map((value, i) => {
      const x = (i / Math.max(values.length - 1, 1)) * 100;
      const y = ((100 - (value / max) * 100) / 100) * 28;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const last = values[values.length - 1];
  return (
    <div
      className="bg-panel rounded-card p-3"
    >
      <div className="flex items-baseline justify-between">
        <div className="text-xs text-text-muted">{title}</div>
        <div className="text-sm font-semibold">
          {format ? format(last) : formatAnalyticsNumber(last)}
        </div>
      </div>
      <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="w-full h-12 mt-2">
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="1.2"
          points={points}
          className="text-accent"
        />
      </svg>
    </div>
  );
}

function TopList({
  title,
  entries,
  valueKind,
}: {
  title: string;
  entries: Array<{
    user_id: number;
    username: string | null;
    display_name: string;
    value: unknown;
  }>;
  valueKind: SeriesValueKind;
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
                  <span className="text-text-muted">{formatAdminUsername(e.username)}</span>
                </span>
              </div>
              <span className="font-mono text-text-muted">
                {valueKind === "count" ? formatCountValue(e.value) : formatAnalyticsNumber(e.value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
