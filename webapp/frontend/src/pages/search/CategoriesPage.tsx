import { useParams } from "react-router-dom";
import { Header } from "@/components/layout/Header";
import { Page } from "@/components/layout/Page";
import { CategoryTile } from "@/components/domain/CategoryTile";
import { ServiceCard } from "@/components/domain/ServiceCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useCategories, useServices } from "@/api/hooks";

export default function CategoriesPage() {
  const { slug } = useParams<{ slug?: string }>();
  const { data: categories, isLoading } = useCategories();
  const { data: services, isLoading: servicesLoading } = useServices(slug ? { category: slug } : {});
  const currentCategory = categories?.find((c) => c.slug === slug);

  if (slug) {
    return (
      <Page showBack>
        <Header title={currentCategory?.name ?? "Категория"} subtitle={`Услуг: ${services?.length ?? 0}`} />
        <div className="px-4 space-y-2">
          {servicesLoading ? (
            Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24" />)
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
        {isLoading ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {Array.from({ length: 9 }).map((_, i) => (
              <Skeleton key={i} className="aspect-square" />
            ))}
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
