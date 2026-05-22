import { useNavigate } from "react-router-dom";
import { useState } from "react";
import {
  ArrowUpFromLine,
  Pause,
  Play,
  Plus,
  ShieldCheck,
  Trash2,
  Wallet,
  Settings as SettingsIcon,
  Star,
  Link2,
} from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Button } from "@/components/ui/Button";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { ProfileHeader } from "@/components/domain/ProfileHeader";
import { ProfileStatsGrid } from "@/components/domain/ProfileStatsGrid";
import { ProfileForumsCard } from "@/components/domain/ProfileForumsCard";
import { ProfileFiatBalanceCard } from "@/components/domain/ProfileFiatBalanceCard";
import { ServiceCard } from "@/components/domain/ServiceCard";
import {
  useDeleteService,
  useMe,
  useReviews,
  useServices,
  useUpdateService,
} from "@/api/hooks";
import { haptic } from "@/lib/tg";
import { confirmDialog } from "@/lib/dialog";
import { relativeTime } from "@/lib/format";

export default function ProfilePage() {
  const navigate = useNavigate();
  const { data: me, isLoading } = useMe();
  const [tab, setTab] = useState<"services" | "reviews">("services");
  const { data: services } = useServices({ owner: me?.username });
  const { data: reviews } = useReviews(me?.username);

  const updateService = useUpdateService();
  const deleteService = useDeleteService();

  if (isLoading || !me) {
    return (
      <Page>
        <div className="px-4 space-y-3 pt-3">
          <Skeleton className="h-64" />
          <Skeleton className="h-32" />
        </div>
      </Page>
    );
  }

  return (
    <Page>
      <ProfileHeader user={me} />

      <div className="px-4 mt-3 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <Button variant="primary" onClick={() => navigate("/profile/add-service")}>
            <Plus className="size-4" /> Добавить услугу
          </Button>
          <Button variant="primary" onClick={() => navigate("/wallet")}>
            <Wallet className="size-4" /> Депозит
          </Button>
          {/* Item 23 — surface the withdraw flow next to deposit so
              the user has a direct entry point from the profile.
              Pre-fix the only "Вывести" button lived on the (deeply
              nested) ``ProfileFiatBalanceCard``, and users complained
              they couldn't find a withdraw action at all. */}
          <Button
            variant="secondary"
            onClick={() => navigate("/wallet/withdraw")}
          >
            <ArrowUpFromLine className="size-4" /> Вывести
          </Button>
          <Button
            variant="secondary"
            onClick={() => navigate("/profile/settings")}
          >
            <SettingsIcon className="size-4" /> Настройки
          </Button>
          <Button
            variant="secondary"
            onClick={() => navigate("/profile/add-forum")}
            className="col-span-2"
          >
            <Link2 className="size-4" /> Добавить форумы
          </Button>
          {me.is_admin ? (
            <Button
              variant="primary"
              onClick={() => navigate("/admin")}
              className="col-span-2"
            >
              <ShieldCheck className="size-4" /> Админ-панель
            </Button>
          ) : me.is_arbiter ? (
            <Button
              variant="primary"
              onClick={() => navigate("/admin/arbitration")}
              className="col-span-2"
            >
              <ShieldCheck className="size-4" /> Очередь арбитража
            </Button>
          ) : null}
        </div>

        <ProfileStatsGrid user={me} onDepositClick={() => navigate("/wallet")} />

        <ProfileFiatBalanceCard user={me} />

        <ProfileForumsCard user={me} />

        <ToggleTabs
          value={tab}
          options={[
            { value: "services", label: "Услуги", count: services?.length ?? 0 },
            { value: "reviews", label: "Отзывы", count: reviews?.length ?? 0 },
          ]}
          onChange={setTab}
        />

        {tab === "services" &&
          (!services || services.length === 0 ? (
            <EmptyState title="Услуги отсутствуют" description="Нажмите «Добавить услугу», чтобы добавить первую" />
          ) : (
            services.map((s, i) => (
              <ServiceCard
                key={s.id}
                service={s}
                index={i}
                rightSlot={
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    {s.status !== "banned" && (
                      <button
                        type="button"
                        className="size-8 grid place-items-center rounded-full bg-panel-2 text-text-muted active:scale-95"
                        aria-label={s.status === "active" ? "Поставить на паузу" : "Сделать активной"}
                        onClick={() => {
                          haptic("light");
                          updateService.mutate({
                            id: s.id,
                            body: { status: s.status === "active" ? "paused" : "active" },
                          });
                        }}
                      >
                        {s.status === "active" ? (
                          <Pause className="size-4" />
                        ) : (
                          <Play className="size-4" />
                        )}
                      </button>
                    )}
                    <button
                      type="button"
                      className="size-8 grid place-items-center rounded-full bg-panel-2 text-danger active:scale-95"
                      aria-label="Удалить"
                      onClick={async () => {
                        // Audit L-15 — ``confirmDialog`` uses Telegram’s
                        // native ``showConfirm`` when available and falls
                        // back to ``window.confirm`` outside Telegram.
                        if (await confirmDialog(`Удалить услугу «${s.title}»?`)) {
                          haptic("warning");
                          deleteService.mutate(s.id);
                        }
                      }}
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                }
              />
            ))
          ))}

        {tab === "reviews" &&
          (!reviews || reviews.length === 0 ? (
            <EmptyState
              icon={<Star className="size-5" />}
              title="Отзывов нет"
              description="Завершайте сделки, чтобы получить отзывы"
            />
          ) : (
            reviews.map((r) => (
              <div key={r.id} className="bg-panel border border-border rounded-card p-3">
                <div className="flex items-center gap-2 text-sm">
                  <span className="text-accent font-bold">★ {r.rating.toFixed(1)}</span>
                  <span className="text-text-muted">от @{r.author_username}</span>
                  <span className="text-text-muted ml-auto">{relativeTime(r.created_at)}</span>
                </div>
                {r.text && <div className="mt-2 text-sm">{r.text}</div>}
              </div>
            ))
          ))}
      </div>

    </Page>
  );
}
