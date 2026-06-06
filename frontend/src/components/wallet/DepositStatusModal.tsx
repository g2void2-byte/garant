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
import { useWalletDeposit } from "@/api/hooks";
import { qk } from "@/api/queryKeys";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { usePresence } from "@/lib/animate";
import { normalizeCurrencyCode } from "@/lib/currencyCodes";
import { formatPaymentProvider } from "@/lib/paymentProviders";
import { formatCurrency, parseDecimalValue } from "@/lib/format";
import { parsePositiveIntValue } from "@/lib/routeParams";
import { haptic, openPaymentLink } from "@/lib/tg";
import type { WalletDepositDto } from "@/api/types";

// ``useWalletDeposit`` pulls the polled DTO into ``query.data`` but a
// malformed / empty payload (e.g. catchall ``[]`` in e2e mocks, or a
// transient backend hiccup) would otherwise crash the render on
// ``current.currency.decimals``. Treat anything that doesn't look
// like a DTO as "no fresh data" and fall back to ``initial``.
function isValidDeposit(value: unknown): value is WalletDepositDto {
  return (
    !!value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    "currency" in value &&
    !!(value as WalletDepositDto).currency
  );
}

interface DepositStatusModalProps {
  deposit: WalletDepositDto | null;
  open: boolean;
  onClose: () => void;
  /**
   * Optional callback invoked after the deposit transitions to
   * ``paid`` (in place of ``onClose``). The host page typically
   * navigates the user somewhere meaningful here — e.g. back to
   * ``/profile`` where the credited balance is visible — instead of
   * leaving them on the deposit-creation form.
   */
  onSuccess?: () => void;
  /**
   * Delay before automatically opening the upstream invoice page so
   * the user has a beat to see the modal animate in. Default 1000 ms.
   */
  autoOpenDelayMs?: number;
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
      description: "Платёж получен — баланс уже пополнен.",
    };
  }
  if (status === "expired" || status === "refunded") {
    return {
      label: status === "refunded" ? "Возврат" : "Просрочено",
      tone: "expired",
      Icon: XCircle,
      description:
        status === "refunded"
          ? "Депозит возвращён администратором."
          : "Срок инвойса истёк. Создайте новый, если ещё хотите пополнить.",
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

function openPayUrl(url: string) {
  openPaymentLink(url);
}

/**
 * Real-time deposit invoice status modal.
 *
 * Shown right after ``POST /api/wallet/deposits`` succeeds. Auto-opens
 * the upstream invoice ``pay_url`` after a short delay so the user
 * sees the modal animate in first, then polls
 * ``GET /api/wallet/deposits/{id}`` (every 5 s while ``pending``) and
 * also receives WS push events through ``useLiveNotifications`` —
 * either path invalidates the deposit query and surfaces the new
 * status without a page reload. Closes itself a moment after the
 * status transitions to ``paid`` so the user lands back on the wallet
 * page already credited.
 */
export function DepositStatusModal({
  deposit,
  open,
  onClose,
  onSuccess,
  autoOpenDelayMs = 1000,
}: DepositStatusModalProps) {
  const toast = useToast();
  const qc = useQueryClient();
  const { mounted, visible } = usePresence(open, 200);
  const initial = deposit ?? null;
  const initialDepositId = parsePositiveIntValue(initial?.id);
  const query = useWalletDeposit(open ? initialDepositId : undefined);
  const current = isValidDeposit(query.data) ? query.data : initial;
  const currentDepositId = parsePositiveIntValue(current?.id);
  const currentAmountValue = parseDecimalValue(current?.amount);
  const canAutoOpenProvider =
    current?.status === "pending" &&
    !!current.pay_url &&
    currentAmountValue !== null &&
    currentAmountValue > 0;

  // Track which deposit we've already auto-opened so reopening the
  // modal for a different deposit fires the timer again, but a
  // background refetch on the same deposit doesn't reopen the
  // already-shown invoice in the user's browser.
  const autoOpenedRef = useRef<number | string | null>(null);
  useEffect(() => {
    if (!open || !current?.pay_url || !canAutoOpenProvider) return;
    const autoOpenKey = currentDepositId ?? current.pay_url;
    if (autoOpenedRef.current === autoOpenKey) return;
    autoOpenedRef.current = autoOpenKey;
    const payUrl = current.pay_url;
    const t = setTimeout(() => {
      openPayUrl(payUrl);
    }, autoOpenDelayMs);
    return () => clearTimeout(t);
  }, [open, currentDepositId, current?.pay_url, canAutoOpenProvider, autoOpenDelayMs]);

  // Auto-close shortly after a successful payment so the user sees
  // the "Оплачено" state, the success haptic fires, and then they're
  // dropped back on the wallet page with the credited balance. Host
  // pages that want to navigate elsewhere after the credit (e.g.
  // ``/profile`` to show the new balance) can opt in via
  // ``onSuccess`` — it replaces ``onClose`` only for the ``paid``
  // transition; ``expired`` / ``refunded`` still fall through to the
  // regular close path.
  const lastStatus = useRef<string | undefined>();
  useEffect(() => {
    if (!open || !current) return;
    if (lastStatus.current !== "paid" && current.status === "paid") {
      haptic("success");
      // Real-time balance refresh: the polled deposit DTO is the
      // earliest authoritative signal that funds landed on the
      // backend. Invalidate the wallet caches immediately so the
      // updated balance is already in flight when the modal
      // auto-closes 1.8s later (instead of relying on a WS
      // ``notification`` frame that may have been missed if the WS
      // dropped or the user's tab was inactive). Also nudge
      // ``/api/me`` because the profile card surfaces deposit
      // counters.
      void qc.invalidateQueries({ queryKey: qk.wallet.all() });
      void qc.invalidateQueries({ queryKey: qk.me() });
      const finish = onSuccess ?? onClose;
      const t = setTimeout(finish, 1800);
      lastStatus.current = current.status;
      return () => clearTimeout(t);
    }
    lastStatus.current = current.status;
  }, [open, current, onClose, onSuccess, qc]);

  // Reset the cached "auto-opened" + "last status" state whenever the
  // modal closes so a follow-up deposit starts from a clean slate.
  useEffect(() => {
    if (!open) {
      autoOpenedRef.current = null;
      lastStatus.current = undefined;
    }
  }, [open]);

  const [refreshing, setRefreshing] = useState(false);
  async function refresh() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await query.refetch();
      haptic("light");
    } catch (e: unknown) {
      const msg = (e as Error)?.message ?? "";
      // The wallet-poll endpoint is rate-limited to a few requests
      // per minute server-side; surface 429s as a friendly toast
      // instead of letting the modal swallow them silently.
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

  async function copyInvoice() {
    if (!current?.invoice_id) return;
    try {
      await navigator.clipboard.writeText(current.invoice_id);
      haptic("light");
      toast.show({ kind: "success", title: "ID инвойса скопирован" });
    } catch {
      toast.show({ kind: "error", title: "Не удалось скопировать" });
    }
  }

  if (!mounted || !current) return null;
  const badge = badgeFor(current.status);
  const isPending = current.status === "pending";
  const decimals = current.currency.decimals;
  const currencyCode = normalizeCurrencyCode(current.currency.code) ?? "USD";
  const providerLabel = formatPaymentProvider(current.provider);
  const formattedAmount =
    currentAmountValue !== null && currentAmountValue >= 0
      ? formatCurrency(currentAmountValue, currencyCode, decimals)
      : `\u2014 ${currencyCode}`;
  const canOpenProvider =
    isPending && !!current.pay_url && currentAmountValue !== null && currentAmountValue > 0;

  const body = (
    <div role="dialog" aria-modal="true" aria-labelledby="deposit-status-title">
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
          data-testid="deposit-status-modal"
          className={cn(
            "pointer-events-auto w-full max-w-sm rounded-3xl bg-panel border border-border shadow-pop p-6",
            "transform transition-all duration-200",
            visible ? "scale-100 opacity-100" : "scale-95 opacity-0",
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2
                id="deposit-status-title"
                className="text-[18px] font-semibold tracking-tight text-text"
              >
                Пополнение баланса
              </h2>
              <p className="text-[12px] text-text-muted">
                {providerLabel} · {formattedAmount}
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
              <div className="text-text-muted">Сумма</div>
              <div className="text-text font-medium">
                {formattedAmount}
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
              <div className="text-text font-medium truncate" title={current.invoice_id}>
                {current.invoice_id}
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
            <Button
              size="md"
              onClick={() => {
                if (canOpenProvider && current.pay_url) openPayUrl(current.pay_url);
              }}
              disabled={!canOpenProvider}
              className="!h-11"
            >
              <ExternalLink className="size-4" />
              Открыть оплату
            </Button>
          </div>
          {isPending && (
            <p className="mt-3 text-[11px] text-text-muted text-center leading-relaxed">
              Окно закроется автоматически, когда платёж зайдёт. Не нужно
              перезагружать страницу.
            </p>
          )}
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") return body;
  return createPortal(body, document.body);
}
