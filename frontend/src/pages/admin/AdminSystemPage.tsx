import { useNavigate } from "react-router-dom";
import { Database, Activity, Bot, ShieldAlert, RotateCcw } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { confirmDialog } from "@/lib/dialog";
import { useAdminFlushRedis, useAdminSystemStatus } from "@/api/admin/hooks";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

/**
 * `/admin/system` — service-health introspection.
 *
 * Polls `/api/admin/system/status` every 10 seconds. Each major service
 * gets a green/yellow/red lamp + latency. CryptoBot and bot tokens are
 * reported as "configured" only when set to a non-placeholder value.
 */
export default function AdminSystemPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useAdminSystemStatus();
  const flush = useAdminFlushRedis();
  const toast = useToast();

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  return (
    <Page showBack onBack={() => navigate("/admin")}>
      <AdminHeader title="Система" subtitle="Сервисы и инфраструктура" />
      <div className="px-4 space-y-2 pb-24">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-16 rounded-card" />
          ))
        ) : (
          data && (
            <>
              <Lamp
                ok={data.db_ok}
                icon={<Database size={14} />}
                label="Postgres"
                detail={
                  data.db_latency_ms !== null
                    ? `${data.db_latency_ms.toFixed(1)}ms`
                    : "недоступен"
                }
              />
              <Lamp
                ok={data.redis_ok}
                icon={<Activity size={14} />}
                label="Redis"
                detail={
                  data.redis_latency_ms !== null
                    ? `${data.redis_latency_ms.toFixed(1)}ms`
                    : "не настроен / недоступен"
                }
                warningIfOff
              />
              <Lamp
                ok={data.bot_configured}
                icon={<Bot size={14} />}
                label="Telegram Bot"
                detail={data.bot_configured ? "токен настроен" : "токен не задан"}
              />
              <Lamp
                ok={data.cryptobot_configured}
                icon={<ShieldAlert size={14} />}
                label="CryptoBot"
                detail={
                  data.cryptobot_configured
                    ? "API ключ настроен"
                    : "API ключ не задан"
                }
              />
              <div
                className="bg-panel rounded-card p-3 text-xs text-text-muted space-y-1"
              >
                <div>Версия: {data.backend_version}</div>
                <div>
                  Аптайм: {formatUptime(data.uptime_seconds)}
                  {data.started_at && ` (с ${new Date(data.started_at).toLocaleString()})`}
                </div>
              </div>

              <div className="pt-2">
                <Button
                  type="button"
                  variant="danger"
                  disabled={flush.isPending || !data.redis_ok}
                  onClick={async () => {
                    // Audit L-15 — ``confirmDialog`` prefers Telegram’s native
                    // ``showConfirm``; falls back to ``window.confirm`` outside Telegram.
                    if (!(await confirmDialog("Очистить все ключи в Redis? Это сбросит кеши и блокировки."))) return;
                    try {
                      const res = await flush.mutateAsync();
                      toast.show({
                        kind: res.ok ? "success" : "error",
                        title: res.ok ? "Redis очищен" : "Ошибка",
                        body: res.message,
                      });
                    } catch (e) {
                      toast.show({
                        kind: "error",
                        title: "Ошибка",
                        body: (e as Error).message,
                      });
                    }
                  }}
                  className="w-full"
                >
                  <RotateCcw size={14} className="mr-1" /> Очистить Redis
                </Button>
              </div>
            </>
          )
        )}
      </div>
    </Page>
  );
}

function Lamp({
  ok,
  icon,
  label,
  detail,
  warningIfOff,
}: {
  ok: boolean;
  icon: React.ReactNode;
  label: string;
  detail?: string;
  warningIfOff?: boolean;
}) {
  const color = ok
    ? "bg-success/15 text-success"
    : warningIfOff
      ? "bg-warning/15 text-warning"
      : "bg-danger/15 text-danger";
  return (
    <div
      className="bg-panel rounded-card p-3 flex items-center gap-3"
    >
      <div className={`size-9 rounded-full grid place-items-center ${color}`}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium">{label}</div>
        {detail && <div className="text-xs text-text-muted truncate">{detail}</div>}
      </div>
      <div
        className={`size-2.5 rounded-full ${
          ok
            ? "bg-success"
            : warningIfOff
              ? "bg-warning"
              : "bg-danger"
        }`}
      />
    </div>
  );
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ${m % 60}m`;
  const d = Math.floor(h / 24);
  return `${d}d ${h % 24}h`;
}
