import { useNavigate } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import {
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
  buildReviewsSearchParams,
  buildServicesSearchParams,
  useDeleteService,
  useMe,
  useReviews,
  useServices,
  useUpdateService,
} from "@/api/hooks";
import { api } from "@/api/client";
import type { ReviewDto, ServiceDto } from "@/api/types";
import { haptic } from "@/lib/tg";
import { confirmDialog } from "@/lib/dialog";
import { formatRatingValue, relativeTime } from "@/lib/format";
import { normalizeUsernameRef } from "@/lib/usernames";

const PROFILE_REVIEWS_PAGE_SIZE = 50;
const PROFILE_SERVICES_PAGE_SIZE = 50;

export default function ProfilePage() {
  const navigate = useNavigate();
  const { data: me, isLoading } = useMe();
  const myUsername = normalizeUsernameRef(me?.username);
  const [tab, setTab] = useState<"services" | "reviews">("services");
  // Audit (continuation) L-2 — gate the services query on having a
  // resolved ``owner`` so the first render (while ``useMe`` is still
  // loading) doesn't issue a list-all request and pollute the
  // TanStack Query cache with someone else's data. ``useReviews``
  // already does this via its own ``enabled`` guard.
  const firstServicesParams = useMemo(
    () => ({ owner: myUsername ?? undefined, limit: PROFILE_SERVICES_PAGE_SIZE, offset: 0 }),
    [myUsername],
  );
  const { data: services } = useServices(
    firstServicesParams,
    { enabled: !!myUsername },
  );
  const [serviceItems, setServiceItems] = useState<ServiceDto[]>([]);
  const [servicesReachedEnd, setServicesReachedEnd] = useState(false);
  const [loadingMoreServices, setLoadingMoreServices] = useState(false);
  const [servicesError, setServicesError] = useState<string | null>(null);
  const firstReviewsParams = useMemo(
    () => ({ limit: PROFILE_REVIEWS_PAGE_SIZE, offset: 0 }),
    [],
  );
  const { data: reviews } = useReviews(myUsername ?? undefined, firstReviewsParams);
  const [reviewItems, setReviewItems] = useState<ReviewDto[]>([]);
  const [reviewsReachedEnd, setReviewsReachedEnd] = useState(false);
  const [loadingMoreReviews, setLoadingMoreReviews] = useState(false);
  const [reviewsError, setReviewsError] = useState<string | null>(null);

  useEffect(() => {
    const page = reviews ?? [];
    setReviewItems(page);
    setReviewsReachedEnd(page.length < PROFILE_REVIEWS_PAGE_SIZE);
    setReviewsError(null);
  }, [reviews, myUsername]);

  const loadMoreReviews = async () => {
    if (!myUsername || loadingMoreReviews || reviewsReachedEnd) return;
    setLoadingMoreReviews(true);
    setReviewsError(null);
    try {
      const page = await api
        .get("api/reviews", {
          searchParams: buildReviewsSearchParams(myUsername, {
            limit: PROFILE_REVIEWS_PAGE_SIZE,
            offset: reviewItems.length,
          }),
        })
        .json<ReviewDto[]>();
      setReviewItems((prev) => [...prev, ...page]);
      if (page.length < PROFILE_REVIEWS_PAGE_SIZE) setReviewsReachedEnd(true);
    } catch (e: unknown) {
      setReviewsError((e as Error)?.message || "Не удалось загрузить еще отзывы");
    } finally {
      setLoadingMoreReviews(false);
    }
  };

  const hasMoreReviews =
    !reviewsReachedEnd &&
    reviewItems.length >= PROFILE_REVIEWS_PAGE_SIZE &&
    reviewItems.length < (me?.reviews_count ?? 0);

  useEffect(() => {
    const page = services ?? [];
    setServiceItems(page);
    setServicesReachedEnd(page.length < PROFILE_SERVICES_PAGE_SIZE);
    setServicesError(null);
  }, [services, myUsername]);

  const loadMoreServices = async () => {
    if (!myUsername || loadingMoreServices || servicesReachedEnd) return;
    setLoadingMoreServices(true);
    setServicesError(null);
    try {
      const page = await api
        .get("api/services", {
          searchParams: buildServicesSearchParams({
            owner: myUsername,
            limit: PROFILE_SERVICES_PAGE_SIZE,
            offset: serviceItems.length,
          }),
        })
        .json<ServiceDto[]>();
      setServiceItems((prev) => [...prev, ...page]);
      if (page.length < PROFILE_SERVICES_PAGE_SIZE) setServicesReachedEnd(true);
    } catch (e: unknown) {
      setServicesError((e as Error)?.message || "Не удалось загрузить еще услуги");
    } finally {
      setLoadingMoreServices(false);
    }
  };

  const hasMoreServices =
    !servicesReachedEnd && serviceItems.length >= PROFILE_SERVICES_PAGE_SIZE;

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
        {/* Балансовая карточка теперь первой под шапкой — пользователь
            видит текущий баланс выбранной фиатной валюты сразу, без
            прокрутки, и оттуда же попадает в Пополнить / Вывести.
            Соответственно дубликат «Вывести» из верхней сетки удалён —
            единственная точка входа в withdraw теперь живёт здесь
            (как и до Item-23). */}
        <ProfileFiatBalanceCard user={me} />

        <div className="grid grid-cols-2 gap-2">
          <Button variant="primary" onClick={() => navigate("/profile/add-service")}>
            <Plus className="size-4" /> Добавить услугу
          </Button>
          <Button variant="primary" onClick={() => navigate("/wallet")}>
            <Wallet className="size-4" /> Депозит
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

        <ProfileStatsGrid user={me} onDepositClick={() => navigate("/wallet/trust-deposit")} />

        <ProfileForumsCard user={me} />

        <ToggleTabs
          value={tab}
          options={[
            { value: "services", label: "Услуги", count: serviceItems.length },
            { value: "reviews", label: "Отзывы", count: me.reviews_count },
          ]}
          onChange={setTab}
        />

        {tab === "services" &&
          (serviceItems.length === 0 ? (
            <EmptyState title="Услуги отсутствуют" description="Нажмите «Добавить услугу», чтобы добавить первую" />
          ) : (
            <>
              {serviceItems.map((s, i) => (
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
              ))}
              {hasMoreServices && (
                <Button onClick={loadMoreServices} disabled={loadingMoreServices} className="w-full">
                  {loadingMoreServices ? "Загружаю..." : "Показать еще"}
                </Button>
              )}
              {servicesError && <div className="text-xs text-danger text-center">{servicesError}</div>}
            </>
          ))}

        {tab === "reviews" &&
          (reviewItems.length === 0 ? (
            <EmptyState
              icon={<Star className="size-5" />}
              title="Отзывов нет"
              description="Завершайте сделки, чтобы получить отзывы"
            />
          ) : (
            <>
              {reviewItems.map((rawReview) => {
                const r = {
                  ...rawReview,
                  author_username: normalizeUsernameRef(rawReview.author_username),
                };
                return (
              <div key={r.id} className="bg-panel border border-border rounded-card p-3">
                <div className="flex items-center gap-2 text-sm">
                  {/* Audit (continuation) M-2 — defence-in-depth.
                      ``r.rating`` is typed as ``number`` in the
                      OpenAPI client, but it round-trips through
                      Pydantic's ``Decimal`` serializer and a future
                      ``json_encoders`` change could surface it as a
                      JSON string. ``formatRatingValue`` accepts strict decimal shapes,
                      so malformed/exponent payloads render as a neutral dash. */}
                  <span className="text-accent font-bold">★ {formatRatingValue(r.rating)}</span>
                  <span className="text-text-muted">
                    {r.author_username ? `от @${r.author_username}` : "автор недоступен"}
                  </span>
                  <span className="text-text-muted ml-auto">{relativeTime(r.created_at)}</span>
                </div>
                {r.text && <div className="mt-2 text-sm">{r.text}</div>}
              </div>
                );
              })}
              {hasMoreReviews && (
                <Button onClick={loadMoreReviews} disabled={loadingMoreReviews} className="w-full">
                  {loadingMoreReviews ? "Загружаю..." : "Показать еще"}
                </Button>
              )}
              {reviewsError && <div className="text-xs text-danger text-center">{reviewsError}</div>}
            </>
          ))}
      </div>

    </Page>
  );
}
