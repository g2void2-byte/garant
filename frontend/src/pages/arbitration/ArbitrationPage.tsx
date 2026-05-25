import { useQuery } from "@tanstack/react-query";
import { Gavel } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { DealRow } from "@/components/domain/DealRow";
import { api } from "@/api/client";
import { useMe } from "@/api/hooks";
import { qk } from "@/api/queryKeys";
import type { DealDto } from "@/api/types";

/**
 * Continental "Арбитраж" page.
 *
 * Regular users see arbitration cases they're a party to. Arbiters /
 * admins see the system-wide list and can pick a case up by tapping it.
 * Empty states match Continental strings: "Арбитры не найдены" for
 * non-arbiters with zero cases, and a generic empty state for arbiters.
 */
export default function ArbitrationPage() {
  const { data: me } = useMe();
  const { data, isLoading } = useQuery<DealDto[]>({
    queryKey: qk.arbitration.deals(),
    queryFn: () => api.get("api/arbitration/deals").json(),
    staleTime: 15_000,
  });

  const isArbiter = !!(me?.is_admin || me?.is_arbiter);
  const subtitle = isArbiter
    ? "Все споры в системе"
    : "Ваши открытые и закрытые споры";

  return (
    <Page>
      <Header title="Арбитраж" subtitle={subtitle} />
      <div className="px-4 space-y-2">
        {isLoading && (
          <>
            <Skeleton className="h-24 w-full rounded-card" />
            <Skeleton className="h-24 w-full rounded-card" />
            <Skeleton className="h-24 w-full rounded-card" />
          </>
        )}
        {!isLoading && (!data || data.length === 0) && (
          <EmptyState
            icon={<Gavel className="size-8" />}
            title={isArbiter ? "Споров пока нет" : "Арбитры не найдены"}
            description={
              isArbiter
                ? "Здесь будут появляться сделки, переведённые в арбитраж."
                : "У вас нет открытых или закрытых споров."
            }
          />
        )}
        {!isLoading &&
          data?.map((deal, i) => <DealRow key={deal.id} deal={deal} index={i} />)}
      </div>
    </Page>
  );
}
