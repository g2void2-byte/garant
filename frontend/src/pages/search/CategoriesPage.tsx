import { useParams } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { Header } from "@/components/layout/Header";
import { Page } from "@/components/layout/Page";
import { CategoryTile } from "@/components/domain/CategoryTile";
import { ServiceCard } from "@/components/domain/ServiceCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { buildServicesSearchParams, useCategories, useServices, useMe } from "@/api/hooks";
import { Button } from "@/components/ui/Button";
import { api } from "@/api/client";
import type { ServiceDto } from "@/api/types";
import { formatCountValue, parseNonNegativeIntegerValue } from "@/lib/format";
import { MOCK_CATEGORIES, MOCK_SERVICES } from "./mockData";
import { SearchGateOverlay } from "./SearchGateOverlay";

const CATEGORY_SERVICES_PAGE_SIZE = 50;

export default function CategoriesPage() {
  const { slug } = useParams<{ slug?: string }>();
  const { data: me, isLoading: meLoading } = useMe();
  const meDealsCount = me ? parseNonNegativeIntegerValue(me.deals_count) : null;
  const isGated = me !== undefined && !me.is_admin && (meDealsCount === null || meDealsCount === 0);
  const { data: categories, isLoading } = useCategories({ enabled: me !== undefined && !isGated });
  const firstServicesParams = useMemo(
    () => ({ category: slug, limit: CATEGORY_SERVICES_PAGE_SIZE, offset: 0 }),
    [slug],
  );
  const { data: services, isLoading: servicesLoading } = useServices(
    firstServicesParams,
    { enabled: me !== undefined && !isGated && !!slug },
  );
  const currentCategory = categories?.find((c) => c.slug === slug);
  const [serviceItems, setServiceItems] = useState<ServiceDto[]>([]);
  const [servicesReachedEnd, setServicesReachedEnd] = useState(false);
  const [loadingMoreServices, setLoadingMoreServices] = useState(false);
  const [servicesError, setServicesError] = useState<string | null>(null);
  const currentCategoryServicesCount = parseNonNegativeIntegerValue(currentCategory?.services_count);
  const currentCategoryServicesCountLabel = currentCategory
    ? formatCountValue(currentCategory.services_count)
    : formatCountValue(serviceItems.length);

  useEffect(() => {
    const page = services ?? [];
    setServiceItems(page);
    setServicesReachedEnd(page.length < CATEGORY_SERVICES_PAGE_SIZE);
    setServicesError(null);
  }, [services, slug]);

  const loadMoreServices = async () => {
    if (!slug || loadingMoreServices || servicesReachedEnd) return;
    setLoadingMoreServices(true);
    setServicesError(null);
    try {
      const page = await api
        .get("api/services", {
          searchParams: buildServicesSearchParams({
            category: slug,
            limit: CATEGORY_SERVICES_PAGE_SIZE,
            offset: serviceItems.length,
          }),
        })
        .json<ServiceDto[]>();
      setServiceItems((prev) => [...prev, ...page]);
      if (page.length < CATEGORY_SERVICES_PAGE_SIZE) setServicesReachedEnd(true);
    } catch (e: unknown) {
      setServicesError((e as Error)?.message || "Не удалось загрузить еще услуги");
    } finally {
      setLoadingMoreServices(false);
    }
  };

  const hasMoreServices =
    !!currentCategory &&
    !servicesReachedEnd &&
    serviceItems.length >= CATEGORY_SERVICES_PAGE_SIZE &&
    currentCategoryServicesCount !== null &&
    serviceItems.length < currentCategoryServicesCount;

  const showSkeleton = meLoading || (!me && !isGated) || isLoading || (slug ? servicesLoading : false);

  if (slug) {
    return (
      <Page showBack>
        <Header title={currentCategory?.name ?? "Категория"} subtitle={`Услуг: ${currentCategoryServicesCountLabel}`} />
        <div className="px-4 space-y-2">
          {showSkeleton ? (
            Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24" />)
          ) : isGated ? (
            <div className="relative overflow-hidden rounded-card">
              <div className="space-y-2 filter blur-[6px] select-none pointer-events-none">
                {MOCK_SERVICES.map((s, i) => (
                  <ServiceCard key={s.id} service={s} index={i} />
                ))}
              </div>
              <SearchGateOverlay message="В целях безопасности и защиты от спама просмотр каталога услуг доступен только участникам, совершившим хотя бы 1 сделку." />
            </div>
          ) : serviceItems.length === 0 ? (
            <EmptyState title="Услуги отсутствуют" description="Пока никто не добавил услуг в этой категории" />
          ) : (
            <>
              {serviceItems.map((s, i) => <ServiceCard key={s.id} service={s} index={i} />)}
              {hasMoreServices && (
                <Button onClick={loadMoreServices} disabled={loadingMoreServices} className="w-full">
                  {loadingMoreServices ? "Загружаю..." : "Показать еще"}
                </Button>
              )}
              {servicesError && <div className="text-xs text-danger text-center">{servicesError}</div>}
            </>
          )}
        </div>
      </Page>
    );
  }

  return (
    <Page showBack>
      <Header title="Категории" subtitle="Выберите раздел услуг" />
      <div className="px-4">
        {showSkeleton ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {Array.from({ length: 9 }).map((_, i) => (
              <Skeleton key={i} className="aspect-square" />
            ))}
          </div>
        ) : isGated ? (
          <div className="relative overflow-hidden rounded-card">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 filter blur-[6px] select-none pointer-events-none">
              {MOCK_CATEGORIES.map((cat, i) => (
                <CategoryTile key={cat.id} category={cat} index={i} />
              ))}
            </div>
            <SearchGateOverlay message="В целях безопасности и защиты от спама каталог категорий доступен только участникам, совершившим хотя бы 1 сделку." />
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {categories?.map((cat, i) => (
              <CategoryTile key={cat.id} category={cat} index={i} />
            ))}
          </div>
        )}
      </div>
    </Page>
  );
}
