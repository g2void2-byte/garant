import { useParams, useNavigate } from "react-router-dom";
import { Header } from "@/components/layout/Header";
import { Page } from "@/components/layout/Page";
import { CategoryTile } from "@/components/domain/CategoryTile";
import { ServiceCard } from "@/components/domain/ServiceCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { useCategories, useServices, useMe } from "@/api/hooks";
import { MOCK_CATEGORIES, MOCK_SERVICES } from "./mockData";
import { SearchGateOverlay } from "./SearchGateOverlay";

export default function CategoriesPage() {
  const { slug } = useParams<{ slug?: string }>();
  const navigate = useNavigate();
  const { data: me, isLoading: meLoading } = useMe();
  const isGated = me !== undefined && me.deals_count === 0 && !me.is_admin;
  const { data: categories, isLoading } = useCategories({ enabled: me !== undefined && !isGated });
  const { data: services, isLoading: servicesLoading } = useServices(
    slug ? { category: slug } : {},
    { enabled: me !== undefined && !isGated && !!slug },
  );
  const currentCategory = categories?.find((c) => c.slug === slug);

  const showSkeleton = meLoading || (!me && !isGated) || isLoading || (slug ? servicesLoading : false);

  if (slug) {
    return (
      <Page showBack>
        <Header title={currentCategory?.name ?? "Категория"} subtitle={`Услуг: ${services?.length ?? 0}`} />
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
          ) : !services || services.length === 0 ? (
            <EmptyState title="Услуги отсутствуют" description="Пока никто не добавил услуг в этой категории" />
          ) : (
            services.map((s, i) => <ServiceCard key={s.id} service={s} index={i} />)
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
