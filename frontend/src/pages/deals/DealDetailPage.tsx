import { useParams } from "react-router-dom";
import { CheckCircle2, Gavel, X, ThumbsUp } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { useDeal, useDealAction } from "@/api/hooks";
import { formatMoney, relativeTime } from "@/lib/format";
import { haptic } from "@/lib/tg";

export default function DealDetailPage() {
  const { id } = useParams<{ id: string }>();
  const dealId = Number(id);
  const { data: deal, isLoading } = useDeal(dealId);
  const confirm = useDealAction("confirm");
  const complete = useDealAction("complete");
  const cancel = useDealAction("cancel");
  const arbitrate = useDealAction("arbitrate");

  if (isLoading || !deal) {
    return (
      <Page showBack>
        <div className="p-4 space-y-3">
          <Skeleton className="h-12" />
          <Skeleton className="h-40" />
        </div>
      </Page>
    );
  }

  const otherUser = deal.role === "buyer" ? deal.seller : deal.buyer;

  const handle = async (fn: typeof confirm) => {
    try {
      await fn.mutateAsync({ id: dealId });
      haptic("success");
    } catch {
      haptic("error");
    }
  };

  return (
    <Page showBack>
      <Header title={`Сделка #${deal.id}`} subtitle={deal.status} />
      <div className="px-4 space-y-3">
        <div className="bg-panel border border-border rounded-card p-4 space-y-2">
          <div className="text-sm text-text-muted">{deal.role === "buyer" ? "Продавец" : "Покупатель"}</div>
          <div className="text-lg font-semibold">@{otherUser}</div>
          <div className="text-2xl font-bold text-accent">{formatMoney(deal.sum)}</div>
          {deal.created_at && <div className="text-xs text-text-muted">Создано {relativeTime(deal.created_at)}</div>}
        </div>

        <div className="bg-panel border border-border rounded-card p-4">
          <div className="text-sm text-text-muted mb-1">Описание</div>
          <div>{deal.description}</div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {deal.status === "WAIT_CONFIRM" && (
            <>
              <Button onClick={() => handle(confirm)} disabled={confirm.isPending}>
                <CheckCircle2 className="size-4" /> Подтвердить
              </Button>
              <Button variant="danger" onClick={() => handle(cancel)} disabled={cancel.isPending}>
                <X className="size-4" /> Отменить
              </Button>
            </>
          )}
          {(deal.status === "CONFIRMED" || deal.status === "WAIT_FINAL_CONFIRM") && deal.role === "buyer" && (
            <Button className="col-span-2" onClick={() => handle(complete)} disabled={complete.isPending}>
              <ThumbsUp className="size-4" /> Подтвердить исполнение
            </Button>
          )}
          {(deal.status === "CONFIRMED" || deal.status === "WAIT_FINAL_CONFIRM") && (
            <Button
              variant="secondary"
              className="col-span-2"
              onClick={() => handle(arbitrate)}
              disabled={arbitrate.isPending}
            >
              <Gavel className="size-4" /> Открыть арбитраж
            </Button>
          )}
        </div>
      </div>
    </Page>
  );
}
