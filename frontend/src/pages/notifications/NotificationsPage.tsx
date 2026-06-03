import { useEffect, useMemo, useState } from "react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { NotificationRow } from "@/components/domain/NotificationRow";
import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import {
  buildNotificationsSearchParams,
  useMarkAllRead,
  useMarkNotificationRead,
  useMe,
  useNotificationCounters,
  useNotifications,
  useUpdateMe,
} from "@/api/hooks";
import { api } from "@/api/client";
import type { NotificationDto, NotificationType } from "@/api/types";
import { dayKey } from "@/lib/format";
import { haptic } from "@/lib/tg";

type CounterTab = "all" | NotificationType;

const TABS: { value: CounterTab; label: string }[] = [
  { value: "all", label: "Все" },
  { value: "deals", label: "Сделки" },
  { value: "deposits", label: "Депозиты" },
  { value: "system", label: "Системные" },
];

const NOTIFICATIONS_PAGE_SIZE = 50;

export default function NotificationsPage() {
  const [tab, setTab] = useState<CounterTab>("all");
  const { data: counters } = useNotificationCounters();
  const [items, setItems] = useState<NotificationDto[]>([]);
  const [reachedEnd, setReachedEnd] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const type = tab === "all" ? undefined : tab;
  const firstPageParams = useMemo(
    () => ({ type, limit: NOTIFICATIONS_PAGE_SIZE }),
    [type],
  );
  const { data, isLoading } = useNotifications(firstPageParams);
  const { data: me } = useMe();
  const updateMe = useUpdateMe();
  const markRead = useMarkNotificationRead();
  const markAll = useMarkAllRead();

  const markNotificationRead = (id: number) => {
    setItems((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
    markRead.mutate(id);
  };

  const markAllVisibleRead = () => {
    setItems((prev) => prev.map((n) => ({ ...n, is_read: true })));
    markAll.mutate();
  };

  useEffect(() => {
    const page = data ?? [];
    setItems(page);
    setReachedEnd(page.length < NOTIFICATIONS_PAGE_SIZE);
    setLoadMoreError(null);
  }, [data]);

  const loadMoreNotifications = async () => {
    const last = items.at(-1);
    if (!last || loadingMore || reachedEnd) return;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const page = await api
        .get("api/notifications", {
          searchParams: buildNotificationsSearchParams({
            type,
            limit: NOTIFICATIONS_PAGE_SIZE,
            before_created_at: last.created_at,
            before_id: last.id,
          }),
        })
        .json<NotificationDto[]>();
      setItems((prev) => [...prev, ...page]);
      if (page.length < NOTIFICATIONS_PAGE_SIZE) {
        setReachedEnd(true);
      }
    } catch (e: unknown) {
      setLoadMoreError(
        (e as Error)?.message ||
          "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0435\u0449\u0435 \u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u0439",
      );
    } finally {
      setLoadingMore(false);
    }
  };

  const toggleDm = (key: "dm_deals" | "dm_deposits" | "dm_system", value: boolean) => {
    haptic("light");
    updateMe.mutate({ [key]: value });
  };

  const grouped = useMemo(() => {
    const map = new Map<string, typeof data>();
    items.forEach((n) => {
      const key = dayKey(n.created_at);
      const arr = map.get(key) ?? [];
      arr.push(n);
      map.set(key, arr);
    });
    return Array.from(map.entries());
  }, [items]);

  return (
    <Page>
      <Header
        title="Оповещения"
        subtitle={counters && counters.unread > 0 ? `${counters.unread} непрочитанных` : undefined}
        right={
          counters && counters.unread > 0 ? (
            <Button size="sm" variant="ghost" onClick={markAllVisibleRead}>
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
            count: counters ? counters[t.value] : undefined,
          }))}
          onChange={setTab}
        />

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <EmptyState title="Уведомлений нет" description="Уведомления будут появляться здесь" />
        ) : (
          <>
            <div className="space-y-4">
              {grouped.map(([day, rows]) => (
                <section key={day}>
                  <div className="text-xs uppercase tracking-wide text-text-muted px-1 pb-2">{day}</div>
                  <div className="space-y-2">
                    {rows!.map((n, i) => (
                      <NotificationRow
                        key={n.id}
                        item={n}
                        index={i}
                        onRead={markNotificationRead}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
            {!reachedEnd && items.length >= NOTIFICATIONS_PAGE_SIZE && (
              <Button onClick={loadMoreNotifications} disabled={loadingMore} className="w-full">
                {loadingMore
                  ? "\u0417\u0430\u0433\u0440\u0443\u0436\u0430\u044e..."
                  : "\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u0435\u0449\u0435"}
              </Button>
            )}
            {loadMoreError && <div className="text-xs text-danger text-center">{loadMoreError}</div>}
          </>
        )}
      </div>
    </Page>
  );
}
