import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { Select } from "@/components/ui/Select";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { DealRow } from "@/components/domain/DealRow";
import { Button } from "@/components/ui/Button";
import { api } from "@/api/client";
import { buildDealsSearchParams, useDeals } from "@/api/hooks";
import type { DealDto } from "@/api/types";

const STATUS_OPTIONS = [
  { value: "", label: "Все статусы" },
  { value: "pending_confirmation", label: "Ожидает подтверждения" },
  { value: "in_progress", label: "В работе" },
  { value: "pending_cancellation", label: "Запрошена отмена" },
  { value: "arbitration", label: "Арбитраж" },
  { value: "completed", label: "Завершена" },
  { value: "resolved_for_buyer", label: "В пользу покупателя" },
  { value: "resolved_for_seller", label: "В пользу продавца" },
  { value: "cancelled", label: "Отменена" },
  { value: "cancelled_for_inactivity", label: "Отмена за неактивность" },
];

const DEALS_PAGE_SIZE = 50;

export default function DealsPage() {
  const navigate = useNavigate();
  const [role, setRole] = useState<"all" | "buyer" | "seller">("all");
  const [status, setStatus] = useState("");
  const [deals, setDeals] = useState<DealDto[]>([]);
  const [reachedEnd, setReachedEnd] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);

  const queryParams = useMemo(
    () => ({ role: role === "all" ? undefined : role, status: status || undefined }),
    [role, status],
  );
  const firstPageParams = useMemo(
    () => ({ ...queryParams, limit: DEALS_PAGE_SIZE, offset: 0 }),
    [queryParams],
  );
  const { data: dealsPage, isLoading } = useDeals(firstPageParams);

  useEffect(() => {
    const page = dealsPage ?? [];
    setDeals(page);
    setReachedEnd(page.length < DEALS_PAGE_SIZE);
    setLoadMoreError(null);
  }, [dealsPage]);

  const loadMoreDeals = async () => {
    if (loadingMore || reachedEnd) return;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const page = await api
        .get("api/deals", {
          searchParams: buildDealsSearchParams({
            ...queryParams,
            limit: DEALS_PAGE_SIZE,
            offset: deals.length,
          }),
        })
        .json<DealDto[]>();
      setDeals((prev) => [...prev, ...page]);
      if (page.length < DEALS_PAGE_SIZE) {
        setReachedEnd(true);
      }
    } catch (e: unknown) {
      setLoadMoreError(
        (e as Error)?.message ||
          "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0435\u0449\u0435 \u0441\u0434\u0435\u043b\u043e\u043a",
      );
    } finally {
      setLoadingMore(false);
    }
  };

  return (
    <Page>
      <Header
        title="Ваши сделки"
        right={
          <Button size="sm" onClick={() => navigate("/deals/new")}>
            <Plus className="size-4" /> Новая
          </Button>
        }
      />
      <div className="px-4 space-y-3">
        <ToggleTabs
          value={role}
          options={[
            { value: "all", label: "Все" },
            { value: "buyer", label: "Покупки" },
            { value: "seller", label: "Продажи" },
          ]}
          onChange={setRole}
        />
        <Select value={status} options={STATUS_OPTIONS} onChange={setStatus} />

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : deals.length === 0 ? (
          <EmptyState title="Сделок пока нет" description="Нажмите «Новая», чтобы создать сделку" />
        ) : (
          <>
            <div className="space-y-2">
              {deals.map((d, i) => (
                <DealRow key={d.id} deal={d} index={i} />
              ))}
            </div>
            {!reachedEnd && deals.length >= DEALS_PAGE_SIZE && (
              <Button onClick={loadMoreDeals} disabled={loadingMore} className="w-full">
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
