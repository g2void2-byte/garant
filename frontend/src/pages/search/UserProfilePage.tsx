import { useNavigate, useParams } from "react-router-dom";
import { useState } from "react";
import { MessageSquare, HandCoins, Flag, Star } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Button } from "@/components/ui/Button";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { ProfileHeader } from "@/components/domain/ProfileHeader";
import { ProfileStatsGrid } from "@/components/domain/ProfileStatsGrid";
import { ProfileForumsCard } from "@/components/domain/ProfileForumsCard";
import { ServiceCard } from "@/components/domain/ServiceCard";
import { useMe, useReviews, useServices, useUser } from "@/api/hooks";
import { openTelegramLink } from "@/lib/tg";
import { relativeTime } from "@/lib/format";

export default function UserProfilePage() {
  const navigate = useNavigate();
  const { username } = useParams<{ username: string }>();
  const { data: me } = useMe();
  const { data: user, isLoading } = useUser(username);
  const isSelf = me?.username === username;

  const [tab, setTab] = useState<"services" | "reviews">("services");
  const { data: services } = useServices({ owner: username });
  const { data: reviews } = useReviews(username);

  if (isLoading || !user) {
    return (
      <Page showBack>
        <div className="px-4 space-y-3">
          <Skeleton className="h-44" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      </Page>
    );
  }

  return (
    <Page showBack>
      <ProfileHeader user={user} />

      <div className="px-4 mt-3 space-y-3">
        {!isSelf && (
          <div className="grid grid-cols-3 gap-2">
            <Button variant="primary" size="md" onClick={() => navigate(`/deals/new?to=${user.username}`)}>
              <HandCoins className="size-4" /> Сделка
            </Button>
            <Button variant="secondary" size="md" onClick={() => openTelegramLink(`https://t.me/${user.username}`)}>
              <MessageSquare className="size-4" /> Написать
            </Button>
            <Button variant="ghost" size="md">
              <Flag className="size-4" /> Жалоба
            </Button>
          </div>
        )}

        <ProfileStatsGrid user={user} />

        <ProfileForumsCard user={user} />

        <ToggleTabs
          value={tab}
          options={[
            { value: "services", label: "Услуги", count: services?.length ?? 0 },
            { value: "reviews", label: "Отзывы", count: reviews?.length ?? 0 },
          ]}
          onChange={setTab}
        />

        {tab === "services" && (
          <div className="space-y-2">
            {!services || services.length === 0 ? (
              <EmptyState title="Услуги отсутствуют" description="Пользователь пока не добавил услуг" />
            ) : (
              services.map((s, i) => <ServiceCard key={s.id} service={s} index={i} />)
            )}
          </div>
        )}

        {tab === "reviews" && (
          <div className="space-y-2">
            {!reviews || reviews.length === 0 ? (
              <EmptyState
                icon={<Star className="size-5" />}
                title="Отзывов нет"
                description="Тут будут собираться отзывы по успешным сделкам"
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
            )}
          </div>
        )}
      </div>
    </Page>
  );
}
