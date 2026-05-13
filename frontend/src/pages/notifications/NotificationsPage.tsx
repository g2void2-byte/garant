import { useMemo, useState } from "react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { NotificationRow } from "@/components/domain/NotificationRow";
import { Button } from "@/components/ui/Button";
import {
  useMarkAllRead,
  useMarkNotificationRead,
  useNotificationCounters,
  useNotifications,
} from "@/api/hooks";
import { dayKey } from "@/lib/format";

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
  const markRead = useMarkNotificationRead();
  const markAll = useMarkAllRead();

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
