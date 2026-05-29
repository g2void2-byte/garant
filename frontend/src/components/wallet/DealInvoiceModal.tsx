import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  CheckCircle2,
  Clock,
  Copy,
  ExternalLink,
  Loader2,
  RefreshCw,
  X,
  XCircle,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useDeal, useWalletDeposit } from "@/api/hooks";
import { qk } from "@/api/queryKeys";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { usePresence } from "@/lib/animate";
import { formatCurrency } from "@/lib/format";
import { haptic, openPaymentLink } from "@/lib/tg";

interface DealInvoiceModalProps {
  open: boolean;
  onClose: () => void;
  dealId: number;
  depositId: number;
  payUrl: string;
  amount: string | number;
  currencyCode: string;
  provider: string;
  canPay?: boolean;
  /** Called when the deal transitions out of ``pending_topup``. */
  onSuccess: (dealId: number) => void;
  autoOpenDelayMs?: number;
  postSuccessDelayMs?: number;
  successTitle?: string;
  successBody?: string;
}

type StatusBadge = {
  label: string;
  tone: "pending" | "paid" | "expired";
  Icon: typeof Loader2;
  description: string;
};

function badgeFor(status: string): StatusBadge {
  if (status === "paid") {
    return {
      label: "Оплачено",
      tone: "paid",
      Icon: CheckCircle2,
      description: "Платёж получен — сейчас откроем сделку.",
    };
  }
  if (status === "expired" || status === "refunded") {
    return {
      label: status === "refunded" ? "Возврат" : "Просрочено",
      tone: "expired",
      Icon: XCircle,
      description:
        status === "refunded"
          ? "Инвойс возвращён администратором."
          : "Срок инвойса истёк. Создайте новый, если ещё хотите оплатить.",
    };
  }
  return {
    label: "Ожидаем оплату",
    tone: "pending",
    Icon: Loader2,
    description:
      "Откройте инвойс в платёжной системе и завершите оплату. Статус обновится автоматически.",
  };
}

/**
 * Real-time deal-invoice status modal.
 *
 * Mirrors :class:`DepositStatusModal` but is wired to a deal: the
 * polled :func:`useDeal` query is the source of truth for "did the
 * payment land" (deal transitions out of ``pending_topup`` exactly
 * when the upstream provider webhook lands). The deposit query is
 * used as a secondary signal — it flips ``paid`` a moment earlier
 * and lets the user see the green check before the auto-navigate.
 */
export function DealInvoiceModal({
  open,
  onClose,
  dealId,
  depositId,
  payUrl,
  amount,
  currencyCode,
  provider,
  canPay = true,
  onSuccess,
  autoOpenDelayMs = 1000,
  postSuccessDelayMs = 1800,
  successTitle = "Сделка создана",
  successBody = "Платёж прошёл. Сейчас откроем сделку.",
}: DealInvoiceModalProps) {
  const toast = useToast();
  const qc = useQueryClient();
  const { mounted, visible } = usePresence(open, 200);

  const depositQuery = useWalletDeposit(open ? depositId : undefined);
  const dealQuery = useDeal(open ? dealId : undefined);

  // Derived status: deal-status leaving ``pending_topup`` is the
  // canonical "paid" signal. ``deposit.status === "paid"`` is the
  // earlier UI hint while the deal-status transition is in flight.
  const dealStatus = dealQuery.data?.status;
  const depositStatus = depositQuery.data?.status ?? "pending";
  const status = depositStatus === "expired" || depositStatus === "refunded"
    ? depositStatus
    : depositStatus === "paid" || (!!dealStatus && dealStatus !== "pending_topup")
      ? "paid"
      : "pending";

  // Auto-open the upstream invoice once per modal session.
  const autoOpenedRef = useRef<number | null>(null);
  useEffect(() => {
    if (!open || !payUrl) return;
    if (autoOpenedRef.current === depositId) return;
    autoOpenedRef.current = depositId;
    const t = setTimeout(() => openPaymentLink(payUrl), autoOpenDelayMs);
    return () => clearTimeout(t);
  }, [open, depositId, payUrl, autoOpenDelayMs]);

  useEffect(() => {
    if (!open || status !== "pending") return;
    const t = setInterval(() => {
      void depositQuery.refetch();
      void dealQuery.refetch();
    }, 2000);
    return () => clearInterval(t);
  }, [open, status, depositQuery, dealQuery]);

  useEffect(() => {
    if (!open) autoOpenedRef.current = null;
  }, [open]);

  const firedSuccessRef = useRef(false);
  useEffect(() => {
    if (!open) {
      firedSuccessRef.current = false;
      return;
    }
    if (status !== "paid" || firedSuccessRef.current) return;
    firedSuccessRef.current = true;
    haptic("success");
    void qc.invalidateQueries({ queryKey: qk.wallet.all() });
    void qc.invalidateQueries({ queryKey: qk.deals.all() });
    void qc.invalidateQueries({ queryKey: qk.deal.detail(dealId) });
    void qc.invalidateQueries({ queryKey: qk.me() });
    toast.show({
      kind: "success",
      title: successTitle,
      body: successBody,
    });
    const closeTimer = setTimeout(() => {
      onClose();
      const navTimer = setTimeout(() => onSuccess(dealId), 180);
      return () => clearTimeout(navTimer);
    }, postSuccessDelayMs);
    return () => clearTimeout(closeTimer);
  }, [open, status, onSuccess, qc, dealId, toast, postSuccessDelayMs, onClose, successTitle, successBody]);

  const [refreshing, setRefreshing] = useState(false);
  async function refresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await Promise.all([depositQuery.refetch(), dealQuery.refetch()]);
      haptic("light");
    } catch (e: unknown) {
      const msg = (e as Error)?.message ?? "";
      if (/429/.test(msg)) {
        toast.show({
          kind: "info",
          title: "Слишком часто",
          body: "Подождите немного перед следующей проверкой.",
        });
      } else {
        toast.show({ kind: "error", title: "Не удалось обновить статус" });
      }
    } finally {
      setTimeout(() => setRefreshing(false), 600);
    }
  }

  const invoiceId = depositQuery.data?.invoice_id ?? String(depositId);
  async function copyInvoice() {
    try {
      await navigator.clipboard.writeText(invoiceId);
      haptic("light");
      toast.show({ kind: "success", title: "ID инвойса скопирован" });
    } catch {
      toast.show({ kind: "error", title: "Не удалось скопировать" });
    }
  }

  if (!mounted) return null;
  const badge = badgeFor(status);
  const isPending = status === "pending";
  const decimals = depositQuery.data?.currency?.decimals ?? 2;
  const providerLabel = provider === "crystalpay" ? "Crystalpay" : "CryptoBot";

  const body = (
    <div role="dialog" aria-modal="true" aria-labelledby="deal-invoice-title">
      <div
        className={cn(
          "fixed inset-0 z-[80] bg-black/70 backdrop-blur-sm transition-opacity duration-200",
          visible ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <div
        className={cn(
          "fixed inset-0 z-[81] grid place-items-center p-4 pointer-events-none",
          "transition-opacity duration-200",
          visible ? "opacity-100" : "opacity-0",
        )}
      >
        <div
          data-testid="deal-invoice-modal"
          className={cn(
            "pointer-events-auto w-full max-w-sm rounded-3xl bg-panel border border-border shadow-pop p-6",
            "transform transition-all duration-200",
            visible ? "scale-100 opacity-100" : "scale-95 opacity-0",
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2
                id="deal-invoice-title"
                className="text-[18px] font-semibold tracking-tight text-text"
              >
                Оплата сделки #{dealId}
              </h2>
              <p className="text-[12px] text-text-muted">
                {providerLabel} · {formatCurrency(amount, currencyCode, decimals)}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Закрыть"
              className="size-9 -mr-1 -mt-1 grid place-items-center rounded-full text-text-muted hover:bg-secondary active:scale-95 transition"
            >
              <X className="size-4" />
            </button>
          </div>

          <div
            className={cn(
              "mt-5 flex flex-col items-center gap-3 rounded-2xl border px-4 py-6 text-center transition-colors",
              badge.tone === "paid" && "border-success/40 bg-success/5",
              badge.tone === "expired" && "border-danger/40 bg-danger/5",
              badge.tone === "pending" && "border-border bg-secondary/40",
            )}
          >
            <div
              className={cn(
                "size-16 grid place-items-center rounded-full transition-transform",
                badge.tone === "paid" && "bg-success/15 text-success animate-fade-in-scale",
                badge.tone === "expired" && "bg-danger/15 text-danger animate-fade-in-scale",
                badge.tone === "pending" && "bg-accent/15 text-accent",
              )}
            >
              <badge.Icon
                className={cn(
                  "size-7",
                  badge.tone === "pending" && "animate-spin",
                )}
                strokeWidth={2}
              />
            </div>
            <div className="space-y-1">
              <div className="flex items-center justify-center gap-2 text-[16px] font-semibold text-text">
                {badge.label}
                {badge.tone === "pending" && (
                  <span className="inline-flex items-center gap-1 text-[11px] uppercase tracking-wide text-text-muted">
                    <Clock className="size-3" />
                    realtime
                  </span>
                )}
              </div>
              <p className="text-[13px] text-text-muted leading-relaxed">
                {badge.description}
              </p>
            </div>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-2 text-[12px]">
            <div className="rounded-xl border border-border bg-secondary/30 px-3 py-2">
              <div className="text-text-muted">К оплате</div>
              <div className="text-text font-medium">
                {formatCurrency(amount, currencyCode, decimals)}
              </div>
            </div>
            <button
              type="button"
              onClick={copyInvoice}
              className="rounded-xl border border-border bg-secondary/30 px-3 py-2 text-left transition active:scale-[0.98] hover:bg-secondary/60"
            >
              <div className="flex items-center justify-between gap-1 text-text-muted">
                <span>ID инвойса</span>
                <Copy className="size-3" />
              </div>
              <div className="text-text font-medium truncate" title={invoiceId}>
                {invoiceId}
              </div>
            </button>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={refresh}
              disabled={refreshing}
              className={cn(
                "h-11 rounded-button bg-secondary text-text font-medium transition",
                "flex items-center justify-center gap-2",
                refreshing ? "opacity-60" : "hover:opacity-90 active:opacity-80",
              )}
            >
              <RefreshCw className={cn("size-4", refreshing && "animate-spin")} />
              Проверить
            </button>
            {canPay && isPending && payUrl ? (
              <Button
                size="md"
                onClick={() => openPaymentLink(payUrl)}
                className="!h-11"
              >
                <ExternalLink className="size-4" />
                Открыть оплату
              </Button>
            ) : (
              <div className="rounded-xl border border-border bg-secondary/30 px-3 py-2 text-[12px] leading-relaxed text-text-muted flex items-center justify-center text-center">
                Оплата доступна покупателю. Вы можете только отслеживать статус.
              </div>
            )}
          </div>
          {isPending && (
            <p className="mt-3 text-[11px] text-text-muted text-center leading-relaxed">
              Окно само закроется и откроет сделку, когда платёж зайдёт.
              Не нужно перезагружать страницу.
            </p>
          )}
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") return body;
  return createPortal(body, document.body);
}
