import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  CheckCircle2,
  Gavel,
  X,
  ThumbsUp,
  MessageSquare,
  Star,
  Undo2,
  ShieldCheck,
} from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Textarea } from "@/components/ui/Textarea";
import { DealChatPanel } from "./DealChatPanel";
import {
  useCancelPendingTopup,
  useCreateReview,
  useDeal,
  useDealAction,
  useMe,
  useReviews,
} from "@/api/hooks";
import { formatAmount, parseDecimal, relativeTime } from "@/lib/format";
import { haptic, openPaymentLink, openTelegramLink } from "@/lib/tg";
import { DealInvoiceModal } from "@/components/wallet/DealInvoiceModal";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { parsePositiveIntRouteParam } from "@/lib/routeParams";

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  cancelled: { text: "Отменена", cls: "text-danger" },
  pending_confirmation: { text: "Ожидает подтверждения", cls: "text-accent" },
  pending_payment: { text: "Ожидает оплаты", cls: "text-accent" },
  pending_topup: { text: "Ожидает оплаты инвойса", cls: "text-accent" },
  in_progress: { text: "В работе", cls: "text-success" },
  completed: { text: "Завершена", cls: "text-success" },
  arbitration: { text: "В арбитраже", cls: "text-accent" },
  resolved_for_buyer: { text: "Решено в пользу покупателя", cls: "text-success" },
  resolved_for_seller: { text: "Решено в пользу продавца", cls: "text-success" },
  pending_cancellation: { text: "Запрошена отмена", cls: "text-accent" },
  cancelled_for_inactivity: { text: "Отменена за неактивность", cls: "text-danger" },
};

type WinnerSide = "buyer" | "seller";

function TopupInvoiceRow({
  label,
  value,
  currency,
  strong = false,
}: {
  label: string;
  value: string | number;
  currency?: string;
  strong?: boolean;
}) {
  return (
    <div className={"flex items-center justify-between " + (strong ? "font-semibold" : "")}>
      <span>{label}</span>
      <span>{value}{currency ? ` ${currency}` : ""}</span>
    </div>
  );
}

export default function DealDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const dealId = parsePositiveIntRouteParam(id);
  const { data: deal, isError, isLoading } = useDeal(dealId);
  const { data: me } = useMe();
  const toast = useToast();

  const accept = useDealAction("accept");
  const decline = useDealAction("decline");
  const finish = useDealAction("finish");
  const cancelReq = useDealAction("cancel_request");
  const cancelRevoke = useDealAction("cancel_request/revoke");
  const cancelAccept = useDealAction("cancel_request/accept");
  const debate = useDealAction("debate");
  const resolve = useDealAction("resolve");
  const cancelTopup = useCancelPendingTopup();

  const [debateOpen, setDebateOpen] = useState(false);
  const [debateReason, setDebateReason] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolveSide, setResolveSide] = useState<WinnerSide>("buyer");
  const [resolveNote, setResolveNote] = useState("");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [rating, setRating] = useState(5);
  const [reviewText, setReviewText] = useState("");
  const [invoiceModalOpen, setInvoiceModalOpen] = useState(false);

  const otherUser = deal
    ? deal.role === "buyer"
      ? deal.seller
      : deal.role === "seller"
        ? deal.buyer
        : null
    : null;
  const existingReviewParams: { deal_id?: number; limit: number } = { limit: 1 };
  if (deal) existingReviewParams.deal_id = deal.id;
  const { data: existingReviews } = useReviews(
    otherUser ?? undefined,
    existingReviewParams,
  );
  const createReview = useCreateReview();

  if (!dealId || isError) {
    return (
      <Page showBack>
        <Header title="Сделка" />
        <EmptyState
          title="Сделка не найдена"
          description="Проверьте ссылку или вернитесь к списку сделок."
        />
      </Page>
    );
  }

  if (isLoading) {
    return (
      <Page showBack>
        <div className="p-4 space-y-3">
          <Skeleton className="h-12" />
          <Skeleton className="h-40" />
        </div>
      </Page>
    );
  }

  if (!deal) {
    return (
      <Page showBack>
        <Header title="Сделка" />
        <EmptyState title="Сделка не найдена" />
      </Page>
    );
  }

  const statusInfo =
    STATUS_LABEL[deal.status] ?? { text: deal.status, cls: "text-text-muted" };
  const amount = deal.amount;
  const currency = deal.currency_code ?? "USD";
  const counterpartyLabel = deal.role === "buyer" ? "Продавец" : "Покупатель";
  const counterpartyText = otherUser ? `@${otherUser}` : "Контрагент недоступен";
  const isParticipant = deal.role === "buyer" || deal.role === "seller";
  const isAdmin = !!me && (me.prefix === "admin" || me.prefix === "arbiter");
  const cancelByOther =
    deal.cancellation_initiator &&
    deal.cancellation_initiator !== deal.role &&
    deal.cancellation_initiator !== "other";
  const cancelByMe = deal.cancellation_initiator === deal.role;
  const alreadyReviewed = !!existingReviews?.some(
    (r) => r.deal_id === deal.id && me && r.author_username === me.username,
  );

  const canOpenInvoice = deal.role === "buyer" && deal.status === "pending_topup";
  const showPaidInvoiceState = deal.status !== "pending_topup" && !!deal.topup_invoice;

  const handle = async (
    fn: typeof accept,
    successMsg: string,
    body?: Record<string, unknown>,
  ) => {
    try {
      await fn.mutateAsync({ id: dealId, body });
      haptic("success");
      toast.show({ kind: "success", title: successMsg });
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось выполнить действие",
      });
    }
  };

  const submitDebate = async () => {
    try {
      await debate.mutateAsync({
        id: dealId,
        body: { reason: debateReason },
      });
      haptic("success");
      toast.show({ kind: "success", title: "Арбитраж открыт" });
      setDebateOpen(false);
      setDebateReason("");
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось открыть арбитраж",
      });
    }
  };

  const submitCancel = async () => {
    try {
      await cancelReq.mutateAsync({
        id: dealId,
        body: { reason: cancelReason },
      });
      haptic("success");
      toast.show({ kind: "success", title: "Запрос отмены отправлен" });
      setCancelOpen(false);
      setCancelReason("");
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось запросить отмену",
      });
    }
  };

  const submitResolve = async () => {
    try {
      await resolve.mutateAsync({
        id: dealId,
        body: { winner: resolveSide, note: resolveNote },
      });
      haptic("success");
      toast.show({ kind: "success", title: "Решение по арбитражу вынесено" });
      setResolveOpen(false);
      setResolveNote("");
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось вынести решение",
      });
    }
  };

  const cancelPendingTopup = async () => {
    try {
      await cancelTopup.mutateAsync(dealId);
      haptic("success");
      toast.show({ kind: "success", title: "Инвойс отменён" });
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось отменить инвойс",
      });
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
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось отправить отзыв",
      });
    }
  };

  const canReview =
    !!otherUser &&
    isParticipant &&
    (deal.status === "completed" ||
      deal.status === "resolved_for_buyer" ||
      deal.status === "resolved_for_seller");

  return (
    <Page showBack>
      <Header title={`Сделка #${deal.id}`} subtitle={statusInfo.text} />
      <div className="px-4 space-y-3">
        <div className="bg-panel border border-border rounded-card p-4 space-y-2">
          <div className="text-sm text-text-muted">
            {counterpartyLabel}
          </div>
          {otherUser ? (
            <button
              onClick={() => navigate(`/users/${otherUser}`)}
              className="text-lg font-semibold text-accent active:opacity-80"
            >
              {counterpartyText}
            </button>
          ) : (
            <div className="text-lg font-semibold text-text-muted">{counterpartyText}</div>
          )}
          <div className="text-2xl font-bold text-accent">
            {formatAmount(amount, currency)} {currency}
          </div>
          <div className={cn("text-sm font-semibold", statusInfo.cls)}>
            {statusInfo.text}
          </div>
          {deal.created_at && (
            <div className="text-xs text-text-muted">
              Создано {relativeTime(deal.created_at)}
            </div>
          )}
        </div>

        <div className="bg-panel border border-border rounded-card p-4">
          <div className="text-sm text-text-muted mb-1">Описание</div>
          <div className="whitespace-pre-wrap break-words">{deal.description}</div>
        </div>

        <div className="bg-panel border border-border rounded-card p-4 space-y-2">
          <div className="text-sm text-text-muted">Условия</div>
          <div className="flex items-center justify-between text-sm">
            <span>Комиссия оплачена</span>
            <span className="font-semibold">{deal.commission_paid ? "Да" : "Нет"}</span>
          </div>
          {deal.commission_amount !== null && deal.commission_amount > 0 && (
            <div className="flex items-center justify-between text-sm">
              <span>Размер комиссии</span>
              <span>
                {formatAmount(deal.commission_amount, currency)} {currency}
              </span>
            </div>
          )}
        </div>

        {deal.status === "pending_topup" && (
          <div className="rounded-card border border-border bg-card/80 p-4 space-y-3">
            {(() => {
              const topupInvoice = deal.topup_invoice;
              return (
                <>
                  <div className="text-sm text-text-muted">
                    {deal.role === "buyer"
                      ? `Оплатите инвойс, чтобы сделка активировалась`
                      : otherUser
                        ? `Ожидайте подтверждение сделки от @${otherUser}`
                        : `Ожидайте подтверждение сделки контрагентом`}
                  </div>
                  {topupInvoice && (
                    <div className="space-y-2">
                      <TopupInvoiceRow label="Провайдер" value={topupInvoice.provider === "crystalpay" ? "Crystal Pay" : "CryptoBot"} />
                      {topupInvoice.paid_total && parseDecimal(topupInvoice.paid_total) > 0 && (
                        <TopupInvoiceRow label="Уже оплачено" value={topupInvoice.paid_total} currency={topupInvoice.currency_code} />
                      )}
                      <TopupInvoiceRow label="К оплате сейчас" value={topupInvoice.total} currency={topupInvoice.currency_code} strong />
                      {topupInvoice.expires_at && (
                        <TopupInvoiceRow label="Истекает" value={new Date(topupInvoice.expires_at).toLocaleString()} />
                      )}
                    </div>
                  )}
                  {deal.role === "buyer" && topupInvoice ? (
                    <div className="flex gap-2">
                      <Button onClick={() => openPaymentLink(topupInvoice.pay_url)}>Открыть оплату</Button>
                      <Button
                        variant="danger"
                        onClick={cancelPendingTopup}
                        disabled={cancelTopup.isPending}
                      >
                        {cancelTopup.isPending ? "Отменяю..." : "Отменить"}
                      </Button>
                    </div>
                  ) : null}
                </>
              );
            })()}
          </div>
        )}

        {showPaidInvoiceState && (
          <div className="rounded-card border border-success/30 bg-success/5 p-4 space-y-2">
            <div className="text-sm font-semibold text-success">Инвойс оплачен</div>
            <div className="text-xs text-text-muted">
              История сохранена. Кнопка оплаты больше недоступна.
            </div>
          </div>
        )}

        {invoiceModalOpen && deal.topup_invoice && canOpenInvoice && (
          <DealInvoiceModal
            open={invoiceModalOpen}
            onClose={() => setInvoiceModalOpen(false)}
            dealId={deal.id}
            depositId={deal.topup_invoice.deposit_id}
            payUrl={deal.topup_invoice.pay_url}
            amount={deal.topup_invoice.total}
            currencyCode={deal.topup_invoice.currency_code}
            provider={deal.topup_invoice.provider}
            canPay={canOpenInvoice}
            successTitle="Сделка создана"
            successBody="Платёж прошёл. Сейчас откроем сделку."
            onSuccess={(dealId) => {
              setInvoiceModalOpen(false);
              navigate(`/deals/${dealId}`, { replace: true });
            }}
          />
        )}

        {deal.status === "pending_cancellation" && deal.cancellation_reason && (
          <div className="bg-panel border border-border rounded-card p-4 space-y-1">
            <div className="text-sm text-text-muted">Причина отмены</div>
            <div className="whitespace-pre-wrap break-words">
              {deal.cancellation_reason}
            </div>
          </div>
        )}

        {deal.status === "arbitration" && deal.arbitration_reason && (
          <div className="bg-panel border border-border rounded-card p-4 space-y-1">
            <div className="text-sm text-text-muted">Причина арбитража</div>
            <div className="whitespace-pre-wrap break-words">
              {deal.arbitration_reason}
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          {/* Pending confirmation — seller decides */}
          {deal.status === "pending_confirmation" && deal.role === "seller" && (
            <>
              <Button
                onClick={() => handle(accept, "Сделка принята")}
                disabled={accept.isPending}
              >
                <CheckCircle2 className="size-4" /> Принять
              </Button>
              <Button
                variant="danger"
                onClick={() => handle(decline, "Сделка отклонена")}
                disabled={decline.isPending}
              >
                <X className="size-4" /> Отклонить
              </Button>
            </>
          )}
          {deal.status === "pending_confirmation" && deal.role === "buyer" && (
            <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
              {otherUser
                ? `Ожидаем подтверждения от @${otherUser}`
                : "Ожидаем подтверждения от контрагента"}
            </div>
          )}

          {/* In progress */}
          {deal.status === "in_progress" && deal.role === "buyer" && (
            <Button
              className="col-span-2"
              onClick={() => handle(finish, "Сделка завершена")}
              disabled={finish.isPending}
            >
              <ThumbsUp className="size-4" /> Подтвердить исполнение
            </Button>
          )}
          {deal.status === "in_progress" && deal.role === "seller" && (
            <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
              {otherUser
                ? `Ожидаем подтверждения исполнения от @${otherUser}`
                : "Ожидаем подтверждения исполнения от контрагента"}
            </div>
          )}
          {deal.status === "in_progress" && isParticipant && (
            <>
              <Button
                variant="secondary"
                onClick={() => setCancelOpen(true)}
                disabled={cancelReq.isPending}
              >
                <Undo2 className="size-4" /> Запросить отмену
              </Button>
              <Button
                variant="secondary"
                onClick={() => setDebateOpen(true)}
                disabled={debate.isPending}
              >
                <Gavel className="size-4" /> Арбитраж
              </Button>
            </>
          )}

          {/* Pending cancellation */}
          {deal.status === "pending_cancellation" && cancelByMe && (
            <Button
              className="col-span-2"
              variant="secondary"
              onClick={() => handle(cancelRevoke, "Запрос отмены отозван")}
              disabled={cancelRevoke.isPending}
            >
              <Undo2 className="size-4" /> Отозвать запрос
            </Button>
          )}
          {deal.status === "pending_cancellation" && cancelByOther && (
            <>
              <Button
                variant="danger"
                onClick={() => handle(cancelAccept, "Сделка отменена")}
                disabled={cancelAccept.isPending}
              >
                <CheckCircle2 className="size-4" /> Согласиться на отмену
              </Button>
              <Button
                variant="secondary"
                onClick={() => setDebateOpen(true)}
                disabled={debate.isPending}
              >
                <Gavel className="size-4" /> Арбитраж
              </Button>
            </>
          )}

          {/* Arbitration */}
          {deal.status === "arbitration" && isAdmin && (
            <Button
              className="col-span-2"
              onClick={() => setResolveOpen(true)}
              disabled={resolve.isPending}
            >
              <ShieldCheck className="size-4" /> Вынести решение
            </Button>
          )}
          {deal.status === "arbitration" && !isAdmin && (
            <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
              Сделка в арбитраже. Дождитесь решения арбитра.
            </div>
          )}

          {/* Terminal */}
          {(deal.status === "cancelled" ||
            deal.status === "cancelled_for_inactivity") && (
            <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
              Сделка отменена.
            </div>
          )}

          {canReview && (
            <>
              {!alreadyReviewed ? (
                <Button
                  className="col-span-2"
                  onClick={() => setReviewOpen(true)}
                >
                  <Star className="size-4" /> Оставить отзыв
                </Button>
              ) : (
                <div className="col-span-2 bg-panel border border-border rounded-card p-3 text-sm text-text-muted text-center">
                  Вы уже оставили отзыв
                </div>
              )}
            </>
          )}

          {otherUser && (
            <Button
              variant="ghost"
              className="col-span-2"
              onClick={() => openTelegramLink(`https://t.me/${otherUser}`)}
            >
              <MessageSquare className="size-4" /> Написать @{otherUser}
            </Button>
          )}
        </div>

        {isParticipant && <DealChatPanel dealId={deal.id} />}
      </div>

      <Sheet
        open={cancelOpen}
        onClose={() => setCancelOpen(false)}
        title="Запросить отмену"
      >
        <div className="space-y-3">
          <Textarea
            label="Причина"
            placeholder="Объясните, почему сделку нужно отменить"
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
          />
          <Button
            fullWidth
            variant="danger"
            onClick={submitCancel}
            disabled={cancelReq.isPending}
          >
            {cancelReq.isPending ? "Отправка..." : "Запросить отмену"}
          </Button>
          <div className="text-xs text-text-muted">
            Контрагент сможет согласиться (средства вернутся покупателю), отказаться
            или передать спор в арбитраж.
          </div>
        </div>
      </Sheet>

      <Sheet
        open={debateOpen}
        onClose={() => setDebateOpen(false)}
        title="Открыть арбитраж"
      >
        <div className="space-y-3">
          <Textarea
            label="Опишите ситуацию"
            placeholder="Контрагент не отвечает / не выполнил условия и т. п."
            value={debateReason}
            onChange={(e) => setDebateReason(e.target.value)}
          />
          <Button
            fullWidth
            variant="danger"
            onClick={submitDebate}
            disabled={debate.isPending}
          >
            {debate.isPending ? "Отправка..." : "Открыть арбитраж"}
          </Button>
          <div className="text-xs text-text-muted">
            Арбитр получит уведомление и свяжется с обеими сторонами. До решения
            средства заморожены.
          </div>
        </div>
      </Sheet>

      <Sheet
        open={resolveOpen}
        onClose={() => setResolveOpen(false)}
        title="Решение по арбитражу"
      >
        <div className="space-y-3">
          <div className="text-sm text-text-muted">
            В чью пользу разрешить спор?
          </div>
          <div className="grid grid-cols-2 gap-2">
            {(["buyer", "seller"] as WinnerSide[]).map((side) => (
              <button
                key={side}
                type="button"
                onClick={() => setResolveSide(side)}
                className={cn(
                  "rounded-card border p-3 text-sm font-semibold transition-colors",
                  resolveSide === side
                    ? "bg-accent/15 border-accent text-accent"
                    : "bg-panel-2 border-border",
                )}
              >
                {side === "buyer" ? "Покупателю" : "Продавцу"}
              </button>
            ))}
          </div>
          <Textarea
            label="Комментарий (необязательно)"
            placeholder="Кратко объясните решение"
            value={resolveNote}
            onChange={(e) => setResolveNote(e.target.value)}
          />
          <Button
            fullWidth
            onClick={submitResolve}
            disabled={resolve.isPending}
          >
            {resolve.isPending ? "Отправка..." : "Вынести решение"}
          </Button>
        </div>
      </Sheet>

      <Sheet
        open={reviewOpen}
        onClose={() => setReviewOpen(false)}
        title={otherUser ? `Отзыв на @${otherUser}` : "Отзыв"}
      >
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
                    n <= rating
                      ? "bg-accent/15 border-accent text-accent"
                      : "bg-panel-2 border-border text-text-muted",
                  )}
                  aria-label={`${n} звёзд`}
                >
                  <Star
                    className="size-5"
                    fill={n <= rating ? "currentColor" : "none"}
                  />
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
          <Button
            fullWidth
            onClick={submitReview}
            disabled={createReview.isPending}
          >
            {createReview.isPending ? "Отправка..." : "Опубликовать отзыв"}
          </Button>
        </div>
      </Sheet>
    </Page>
  );
}
