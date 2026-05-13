import { useMemo, useState } from "react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { NotificationRow } from "@/components/domain/NotificationRow";
import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import {
  useMarkAllRead,
  useMarkNotificationRead,
  useMe,
  useNotificationCounters,
  useNotifications,
  useUpdateMe,
} from "@/api/hooks";
import { dayKey } from "@/lib/format";
import { haptic } from "@/lib/tg";

const TABS: { value: "all" | "deals" | "deposits" | "system"; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "deals", label: "Сделки" },
  { value: "deposits", label: "Депозиты" },
  { value: "system", label: "Системные" },
];

export default function NotificationsPage() {
  const [tab, setTab] = useState<"all" | "deals" | "deposits" | "system">("all");
  const { data: counters } = useNotificationCounters();
  const { data, isLoading } = useNotifications(tab === "all" ? undefined : tab);
  const { data: me } = useMe();
  const updateMe = useUpdateMe();
  const markRead = useMarkNotificationRead();
  const markAll = useMarkAllRead();

  const toggleDm = (key: "dm_deals" | "dm_deposits" | "dm_system", value: boolean) => {
    haptic("light");
    updateMe.mutate({ [key]: value });
  };

  const grouped = useMemo(() => {
    const map = new Map<string, typeof data>();
    (data ?? []).forEach((n) => {
      const key = dayKey(n.created_at);
      const arr = map.get(key) ?? [];
      arr.push(n);
      map.set(key, arr);
    });
    return Array.from(map.entries());
  }, [data]);

  return (
    <Page>
      <Header
        title="Оповещения"
        subtitle={counters && counters.unread > 0 ? `${counters.unread} непрочитанных` : undefined}
        right={
          counters && counters.unread > 0 ? (
            <Button size="sm" variant="ghost" onClick={() => markAll.mutate()}>
              Прочитать все
            </Button>
          ) : undefined
        }
      />
      <div className="px-4 space-y-3">
        {me && (
          <details className="bg-panel border border-border rounded-card">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium select-none">
              Присылать в Telegram
            </summary>
            <div className="px-3 pb-3 space-y-3">
              <Switch
                checked={me.dm_deals !== false}
                onChange={(v) => toggleDm("dm_deals", v)}
                label="Сделки"
                description="События ваших сделок (создание, принятие, арбитраж)"
              />
              <Switch
                checked={me.dm_deposits !== false}
                onChange={(v) => toggleDm("dm_deposits", v)}
                label="Депозиты"
                description="Пополнения и выводы"
              />
              <Switch
                checked={me.dm_system !== false}
                onChange={(v) => toggleDm("dm_system", v)}
                label="Системные"
                description="Отзывы, объявления, безопасность"
              />
            </div>
          </details>
        )}
        <ToggleTabs
          value={tab}
          options={TABS.map((t) => ({
            value: t.value,
            label: t.label,
            count: counters ? (counters as any)[t.value] : undefined,
          }))}
          onChange={setTab}
          layoutId="notif-tabs"
        />

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        ) : !data || data.length === 0 ? (
          <EmptyState title="Уведомлений нет" description="Уведомления будут появляться здесь" />
        ) : (
          <div className="space-y-4">
            {grouped.map(([day, items]) => (
              <section key={day}>
                <div className="text-xs uppercase tracking-wide text-text-muted px-1 pb-2">{day}</div>
                <div className="space-y-2">
                  {items!.map((n, i) => (
                    <NotificationRow
                      key={n.id}
                      item={n}
                      index={i}
                      onRead={(id) => markRead.mutate(id)}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </Page>
  );
}
