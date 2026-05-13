import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Gavel, X, ThumbsUp, MessageSquare, Star } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Textarea } from "@/components/ui/Textarea";
import { useCreateReview, useDeal, useDealAction, useMe, useReviews } from "@/api/hooks";
import { formatMoney, relativeTime } from "@/lib/format";
import { haptic, openTelegramLink } from "@/lib/tg";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  wait_confirm: { text: "Ожидает подтверждения", cls: "text-accent" },
  confirmed: { text: "Подтверждена", cls: "text-success" },
  wait_final_confirm: { text: "Финальное подтверждение", cls: "text-accent" },
  success: { text: "Завершена успешно", cls: "text-success" },
  failed: { text: "Отменена", cls: "text-danger" },
  arbitrage: { text: "Арбитраж", cls: "text-accent" },
};

export default function DealDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const dealId = Number(id);
  const { data: deal, isLoading } = useDeal(dealId);
  const { data: me } = useMe();
  const toast = useToast();

  const confirm = useDealAction("confirm");
  const complete = useDealAction("complete");
  const cancel = useDealAction("cancel");
  const arbitrate = useDealAction("arbitrate");

  const [arbitrageOpen, setArbitrageOpen] = useState(false);
  const [arbitrageReason, setArbitrageReason] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [rating, setRating] = useState(5);
  const [reviewText, setReviewText] = useState("");

  const otherUser = deal && (deal.role === "buyer" ? deal.seller : deal.buyer);
  const { data: existingReviews } = useReviews(otherUser);
  const createReview = useCreateReview();

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

  const statusInfo = STATUS_LABEL[deal.status] ?? { text: deal.status, cls: "text-text-muted" };
  const myConfirm = deal.role === "buyer" ? deal.confirm_buyer : deal.confirm_seller;
  const otherConfirm = deal.role === "buyer" ? deal.confirm_seller : deal.confirm_buyer;
  const alreadyReviewed = !!existingReviews?.some(
    (r) => r.deal_id === deal.id && me && r.author_username === me.username,
  );

  const handle = async (fn: typeof confirm, successMsg: string) => {
    try {
      await fn.mutateAsync({ id: dealId });
      haptic("success");
      toast.show({ kind: "success", title: successMsg });
    } catch (e: unknown) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error)?.message || "Не удалось выполнить действие" });
    }
  };

  const submitArbitrage = async () => {
    try {
      await arbitrate.mutateAsync({ id: dealId, reason: arbitrageReason || undefined });
      haptic("success");
      toast.show({ kind: "success", title: "Арбитраж открыт" });
      setArbitrageOpen(false);
      setArbitrageReason("");
    } catch (e: unknown) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error)?.message || "Не удалось открыть арбитраж" });
    }
  };

  const submitReview = async () => {
    if (!otherUser) return;
    try {
      await createReview.mutateAsync({
        target_username: otherUser,
        rating,
        text: reviewText,
        deal_id: deal.id,
      });
      haptic("success");
      toast.show({ kind: "success", title: "Отзыв опубликован" });
      setReviewOpen(false);
      setReviewText("");
    } catch (e: unknown) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error)?.message || "Не удалось отправить отзыв" });
    }
  };

  return (
    <Page showBack>
      <Header title={`Сделка #${deal.id}`} subtitle={statusInfo.text} />
      <div className="px-4 space-y-3">
        <div className="bg-panel border border-border rounded-card p-4 space-y-2">
          <div className="text-sm text-text-muted">{deal.role === "buyer" ? "Продавец" : "Покупатель"}</div>
          <button
            onClick={() => otherUser && navigate(`/u/${otherUser}`)}
            className="text-lg font-semibold text-accent active:opacity-80"
          >
            @{otherUser}
          </button>
          <div className="text-2xl font-bold text-accent">{formatMoney(deal.sum)}</div>
          <div className={cn("text-sm font-semibold", statusInfo.cls)}>{statusInfo.text}</div>
          {deal.created_at && <div className="text-xs text-text-muted">Создано {relativeTime(deal.created_at)}</div>}
        </div>

        <div className="bg-panel border border-border rounded-card p-4">
          <div className="text-sm text-text-muted mb-1">Описание</div>
          <div className="whitespace-pre-wrap break-words">{deal.description}</div>
        </div>

        <div className="bg-panel border border-border rounded-card p-4 space-y-2">
          <div className="text-sm text-text-muted">Условия</div>
          <div className="flex items-center justify-between text-sm">
            <span>Комиссию платит</span>
            <span className="font-semibold">{deal.pay_comission === "buyer" ? "Покупатель" : "Продавец"}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span>Подтверждение покупателя</span>
            <span className={deal.confirm_buyer ? "text-success" : "text-text-muted"}>
              {deal.confirm_buyer ? "✓ есть" : "ожидается"}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span>Подтверждение продавца</span>
            <span className={deal.confirm_seller ? "text-success" : "text-text-muted"}>
              {deal.confirm_seller ? "✓ есть" : "ожидается"}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          {deal.status === "wait_confirm" && !myConfirm && (
            <>
              <Button onClick={() => handle(confirm, "Сделка подтверждена")} disabled={confirm.isPending}>
                <CheckCircle2 className="size-4" /> Подтвердить
              </Button>
              <Button variant="danger" onClick={() => handle(cancel, "Сделка отменена")} disabled={cancel.isPending}>
                <X className="size-4" /> Отменить
              </Button>
            </>
          )}
          {deal.status === "wait_confirm" && myConfirm && !otherConfirm && (
            <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
              Ожидаем подтверждения от @{otherUser}
            </div>
          )}
          {(deal.status === "confirmed" || deal.status === "wait_final_confirm") && deal.role === "buyer" && (
            <Button
              className="col-span-2"
              onClick={() => handle(complete, "Сделка завершена")}
              disabled={complete.isPending}
            >
              <ThumbsUp className="size-4" /> Подтвердить исполнение
            </Button>
          )}
          {(deal.status === "confirmed" || deal.status === "wait_final_confirm") && deal.role === "seller" && (
            <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
              Ожидаем подтверждения исполнения от @{otherUser}
            </div>
          )}
          {(deal.status === "confirmed" || deal.status === "wait_final_confirm") && (
            <Button
              variant="secondary"
              className="col-span-2"
              onClick={() => setArbitrageOpen(true)}
              disabled={arbitrate.isPending}
            >
              <Gavel className="size-4" /> Открыть арбитраж
            </Button>
          )}
          {deal.status === "success" && (
            <>
              {!alreadyReviewed && (
                <Button className="col-span-2" onClick={() => setReviewOpen(true)}>
                  <Star className="size-4" /> Оставить отзыв
                </Button>
              )}
              {alreadyReviewed && (
                <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
                  Вы уже оставили отзыв
                </div>
              )}
            </>
          )}
          {deal.status === "arbitrage" && (
            <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
              Сделка в арбитраже. Дождитесь решения арбитра.
            </div>
          )}
          {deal.status === "failed" && (
            <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
              Сделка отменена.
            </div>
          )}
          <Button
            variant="ghost"
            className="col-span-2"
            onClick={() => otherUser && openTelegramLink(`https://t.me/${otherUser}`)}
          >
            <MessageSquare className="size-4" /> Написать @{otherUser}
          </Button>
        </div>
      </div>

      <Sheet open={arbitrageOpen} onClose={() => setArbitrageOpen(false)} title="Открыть арбитраж">
        <div className="space-y-3">
          <Textarea
            label="Опишите причину (необязательно)"
            placeholder="Контрагент не выполнил условия, не отвечает и т. п."
            value={arbitrageReason}
            onChange={(e) => setArbitrageReason(e.target.value)}
          />
          <Button fullWidth variant="danger" onClick={submitArbitrage} disabled={arbitrate.isPending}>
            {arbitrate.isPending ? "Отправка..." : "Открыть арбитраж"}
          </Button>
          <div className="text-xs text-text-muted">
            Арбитр получит уведомление и свяжется с обеими сторонами. До окончания арбитража средства заморожены.
          </div>
        </div>
      </Sheet>

      <Sheet open={reviewOpen} onClose={() => setReviewOpen(false)} title={`Отзыв на @${otherUser}`}>
        <div className="space-y-3">
          <div>
            <div className="text-sm text-text-muted mb-2">Оценка</div>
            <div className="flex gap-2">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => {
                    setRating(n);
                    haptic("select");
                  }}
                  className={cn(
                    "size-10 grid place-items-center rounded-full border transition-colors",
                    n <= rating ? "bg-accent/15 border-accent text-accent" : "bg-panel-2 border-border text-text-muted",
                  )}
                  aria-label={`${n} звёзд`}
                >
                  <Star className="size-5" fill={n <= rating ? "currentColor" : "none"} />
                </button>
              ))}
            </div>
          </div>
          <Textarea
            label="Комментарий"
            placeholder="Поделитесь впечатлениями"
            value={reviewText}
            onChange={(e) => setReviewText(e.target.value)}
          />
          <Button fullWidth onClick={submitReview} disabled={createReview.isPending}>
            {createReview.isPending ? "Отправка..." : "Опубликовать отзыв"}
          </Button>
        </div>
      </Sheet>
    </Page>
  );
}
