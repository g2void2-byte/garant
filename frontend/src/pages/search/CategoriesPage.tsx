import { useParams, useNavigate } from "react-router-dom";
import { Header } from "@/components/layout/Header";
import { Page } from "@/components/layout/Page";
import { CategoryTile } from "@/components/domain/CategoryTile";
import { ServiceCard } from "@/components/domain/ServiceCard";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { useCategories, useServices, useMe } from "@/api/hooks";
import { ShieldAlert } from "lucide-react";
import { cn } from "@/lib/cn";

const MOCK_CATEGORIES = [
  { id: 901, name: "Социальные сети", slug: "social", icon_key: "more-horizontal", services_count: 24 },
  { id: 902, name: "Криптовалюта", slug: "crypto", icon_key: "bitcoin", services_count: 42 },
  { id: 903, name: "Разработка ботов", slug: "bots", icon_key: "key", services_count: 18 },
  { id: 904, name: "Реклама и пиар", slug: "ads", icon_key: "plane", services_count: 31 },
  { id: 905, name: "UI/UX Дизайн", slug: "design", icon_key: "palette", services_count: 12 },
  { id: 906, name: "Финансовые услуги", slug: "finance", icon_key: "wallet", services_count: 15 },
];

const MOCK_SERVICES = [
  { id: 981, title: "Продажа готового Telegram канала (15к саб)", description: "Канал с живой аудиторией, тематика IT/Бизнес. Чистый доход от рекламы в месяц около 200$. Передача прав полностью через официального гаранта бота.", price: 450, status: "active", owner_username: "social_seller", category: { id: 901, name: "Социальные сети", slug: "social", icon_key: "more-horizontal", services_count: 24 } },
  { id: 982, title: "Быстрый обмен USDT на рубли (СБП/Тинькофф)", description: "Обмениваю чистый USDT TRC20 на рубли. Минималка от 100$. Чистые резервы. Время проведения сделки в среднем 5 минут.", price: 100, status: "active", owner_username: "swift_change", category: { id: 902, name: "Криптовалюта", slug: "crypto", icon_key: "bitcoin", services_count: 42 } },
  { id: 983, title: "Разработка Telegram Mini App под ключ", description: "Качественная разработка мини-приложений (TMA) любой сложности. Стек: React/TypeScript/FastAPI. Сроки от 7 дней.", price: 800, status: "active", owner_username: "tma_dev", category: { id: 903, name: "Разработка ботов", slug: "bots", icon_key: "key", services_count: 18 } },
  { id: 984, title: "Дизайн аватарок и баннеров для каналов", description: "Оформление вашего Telegram канала, создание уникальных аватарок, баннеров и обложек для постов в едином стиле.", price: 50, status: "active", owner_username: "pixel_pro", category: { id: 905, name: "UI/UX Дизайн", slug: "design", icon_key: "palette", services_count: 12 } },
];

export default function CategoriesPage() {
  const { slug } = useParams<{ slug?: string }>();
  const navigate = useNavigate();
  const { data: me, isLoading: meLoading } = useMe();
  const { data: categories, isLoading } = useCategories();
  const { data: services, isLoading: servicesLoading } = useServices(slug ? { category: slug } : {});
  const currentCategory = categories?.find((c) => c.slug === slug);

  const isGated = me && me.deals_count === 0 && !me.is_admin;
  const showSkeleton = isLoading || meLoading || (slug ? servicesLoading : false);

  if (slug) {
    return (
      <Page showBack>
        <Header title={currentCategory?.name ?? "Категория"} subtitle={`Услуг: ${services?.length ?? 0}`} />
        <div className="px-4 space-y-2">
          {showSkeleton ? (
            Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-24" />)
          ) : isGated ? (
            <div className="relative overflow-hidden rounded-card">
              <div className="space-y-2 filter blur-[3.5px] select-none pointer-events-none">
                {MOCK_SERVICES.map((s, i) => (
                  <ServiceCard key={s.id} service={s as any} index={i} />
                ))}
              </div>
              <div className="absolute inset-0 flex flex-col items-center justify-center p-4 bg-black/10 backdrop-blur-[1px] text-center z-10">
                <div className="bg-panel/95 border border-border rounded-2xl p-5 shadow-2xl max-w-sm animate-fade-in-scale">
                  <div className="size-12 mx-auto rounded-full bg-accent/15 text-accent grid place-items-center mb-3">
                    <ShieldAlert className="size-6" />
                  </div>
                  <h3 className="font-semibold text-lg text-text">Поиск ограничен</h3>
                  <p className="text-[13px] text-text-muted mt-2 leading-relaxed">
                    В целях безопасности и защиты от спама просмотр каталога услуг доступен только участникам, совершившим хотя бы 1 сделку.
                  </p>
                  <Button size="sm" className="mt-4 w-full" onClick={() => navigate("/deals")}>
                    Перейти к сделкам
                  </Button>
                </div>
              </div>
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
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 filter blur-[3.5px] select-none pointer-events-none">
              {MOCK_CATEGORIES.map((cat, i) => (
                <CategoryTile key={cat.id} category={cat as any} index={i} />
              ))}
            </div>
            <div className="absolute inset-0 flex flex-col items-center justify-center p-4 bg-black/10 backdrop-blur-[1px] text-center z-10">
              <div className="bg-panel/95 border border-border rounded-2xl p-5 shadow-2xl max-w-sm animate-fade-in-scale">
                <div className="size-12 mx-auto rounded-full bg-accent/15 text-accent grid place-items-center mb-3">
                  <ShieldAlert className="size-6" />
                </div>
                <h3 className="font-semibold text-lg text-text">Поиск ограничен</h3>
                <p className="text-[13px] text-text-muted mt-2 leading-relaxed">
                  В целях безопасности и защиты от спама каталог категорий доступен только участникам, совершившим хотя бы 1 сделку.
                </p>
                <Button size="sm" className="mt-4 w-full" onClick={() => navigate("/deals")}>
                  Перейти к сделкам
                </Button>
              </div>
            </div>
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
