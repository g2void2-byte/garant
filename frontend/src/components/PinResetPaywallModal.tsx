import { useEffect } from "react";
import { createPortal } from "react-dom";
import { CreditCard, Loader2, MessageCircle, X } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useAdmins } from "@/api/hooks";
import { qk } from "@/api/queryKeys";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { usePresence } from "@/lib/animate";
import { haptic, openTelegramLink } from "@/lib/tg";
import { buildTelegramUserUrl } from "@/lib/telegramLinks";
import { formatCurrencyStrict, parseDecimalValue } from "@/lib/format";

interface PinResetPriceDto {
  price: string | number;
  currency_code: string;
  user_balance: string | number;
  can_afford: boolean;
}

interface PinResetPaidDto {
  delivered: boolean;
  expires_at: string;
  charged: string | number;
  currency_code: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  /**
   * Called after the user successfully pays for a reset; the caller
   * typically flips the parent page into the "enter reset code" state.
   */
  onPaid: (result: PinResetPaidDto) => void;
  /**
   * Title shown above the price card. Defaults to the lock-screen
   * wording; the withdraw flow can override with a withdraw-specific
   * line (e.g. "Без PIN-кода вывод недоступен").
   */
  title?: string;
}

/**
 * Paywall modal for the "Забыли PIN" flow. Replaces the previous
 * one-tap-sends-code behaviour with a paid reset:
 *  - shows the admin-configured price + the user's USD balance;
 *  - "Оплатить с баланса" debits the balance and sends the reset
 *    code via Telegram in a single backend transaction;
 *  - "Написать админу" opens a Telegram DM with the first admin
 *    pulled from /api/support/admins;
 *  - "Назад" closes the modal.
 *
 * Mirrors the animation pattern used by ``PinPromptModal`` /
 * ``DepositStatusModal`` so it slots into the existing UI without
 * reinventing the backdrop/scale-in transition.
 */
export function PinResetPaywallModal({
  open,
  onClose,
  onPaid,
  title = "Восстановление PIN-кода",
}: Props) {
  const toast = useToast();
  const qc = useQueryClient();
  const { mounted, visible } = usePresence(open, 200);

  const price = useQuery<PinResetPriceDto>({
    queryKey: ["pin", "reset", "price"],
    queryFn: () => api.get("api/pin/reset/price").json(),
    enabled: open,
    staleTime: 30_000,
  });

  const admins = useAdmins();

  const pay = useMutation<PinResetPaidDto>({
    mutationFn: () => api.post("api/pin/reset/paid").json(),
  });

  const currencyCode = price.data?.currency_code?.trim() || "USD";
  const priceValue = parseDecimalValue(price.data?.price);
  const balanceValue = parseDecimalValue(price.data?.user_balance);
  const hasValidPriceData =
    price.data != null &&
    priceValue !== null &&
    priceValue >= 0 &&
    balanceValue !== null &&
    balanceValue >= 0;
  const priceText =
    price.data != null
      ? formatCurrencyStrict(price.data.price, currencyCode)
      : "\u2014";
  const balanceText =
    price.data != null
      ? formatCurrencyStrict(price.data.user_balance, currencyCode)
      : "\u2014";
  const canAfford =
    hasValidPriceData &&
    !!price.data?.can_afford &&
    balanceValue >= priceValue;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function handlePay() {
    if (!canAfford) return;
    try {
      const res = await pay.mutateAsync();
      haptic("success");
      // Balance changed — keep the wallet/me caches honest so the
      // user sees the deduction the next time they open the wallet.
      void qc.invalidateQueries({ queryKey: qk.wallet.all() });
      void qc.invalidateQueries({ queryKey: qk.me() });
      toast.show({
        kind: "success",
        title: `Списано ${formatCurrencyStrict(res.charged, res.currency_code)}`,
        body: res.delivered
          ? "Код отправлен в Telegram"
          : "Код выписан, но Telegram-сообщение не доставлено",
      });
      onPaid(res);
    } catch (e: unknown) {
      haptic("error");
      const err = e as { message?: string };
      toast.show({
        kind: "error",
        title: err?.message || "Не удалось оплатить восстановление",
      });
    }
  }

  function handleContactAdmin() {
    const admin = admins.data?.[0];
    if (!admin?.username) {
      toast.show({
        kind: "error",
        title: "Список администрации пуст. Попробуйте позже.",
      });
      return;
    }
    const url = buildTelegramUserUrl(admin.username);
    if (url) openTelegramLink(url);
  }

  if (!mounted) return null;

  const body = (
    <>
      <div
        className={cn(
          "fixed inset-0 z-[70] bg-black/70 backdrop-blur-sm transition-opacity duration-200",
          visible ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <div
        className={cn(
          "fixed inset-0 z-[71] grid place-items-center p-4 pointer-events-none",
          visible ? "opacity-100" : "opacity-0",
          "transition-opacity duration-200",
        )}
      >
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="pin-reset-paywall-title"
          data-testid="pin-reset-paywall"
          className={cn(
            "pointer-events-auto w-full max-w-sm rounded-3xl bg-panel border border-border shadow-pop p-6",
            "transform transition-all duration-200",
            visible ? "scale-100 opacity-100" : "scale-95 opacity-0",
          )}
        >
          <div className="flex items-start justify-between">
            <div className="min-w-0">
              <h2
                id="pin-reset-paywall-title"
                className="text-[20px] font-semibold tracking-tight text-text"
              >
                {title}
              </h2>
              <p className="text-text-muted mt-1 text-[14px]">
                Восстановление платное. После оплаты придёт 6-значный код
                в Telegram.
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
              "mt-5 rounded-2xl border border-accent/30 bg-accent/[0.07] p-4",
              "flex items-center justify-between gap-3",
            )}
          >
            <div className="min-w-0">
              <div className="text-text-muted text-[12px] uppercase tracking-wider">
                Стоимость
              </div>
              <div className="text-accent text-[28px] font-bold leading-tight mt-0.5">
                {priceText}
              </div>
            </div>
            <div className="text-right min-w-0">
              <div className="text-text-muted text-[12px] uppercase tracking-wider">
                Ваш баланс
              </div>
              <div
                className={cn(
                  "text-[18px] font-semibold leading-tight mt-0.5",
                  canAfford ? "text-text" : "text-red-400",
                )}
              >
                {balanceText}
              </div>
            </div>
          </div>

          {price.data != null && !hasValidPriceData && (
            <p className="mt-2 text-[12px] text-red-400">
              Не удалось проверить стоимость восстановления. Попробуйте позже или напишите администратору.
            </p>
          )}

          {!canAfford && hasValidPriceData && (
            <p className="mt-2 text-[12px] text-red-400">
              Недостаточно средств для оплаты с баланса. Пополните счёт или
              напишите администратору.
            </p>
          )}

          <div className="mt-5 grid grid-cols-1 gap-2">
            <Button
              variant="primary"
              size="md"
              fullWidth
              disabled={
                price.isLoading || pay.isPending || !canAfford
              }
              onClick={handlePay}
            >
              {pay.isPending ? (
                <Loader2 className="size-4 animate-spin mr-2" />
              ) : (
                <CreditCard className="size-4 mr-2" />
              )}
              Оплатить с баланса
            </Button>
            <Button
              variant="secondary"
              size="md"
              fullWidth
              disabled={admins.isLoading}
              onClick={handleContactAdmin}
            >
              <MessageCircle className="size-4 mr-2" />
              Написать админу
            </Button>
            <Button variant="ghost" size="md" fullWidth onClick={onClose}>
              Назад
            </Button>
          </div>
        </div>
      </div>
    </>
  );

  if (typeof document === "undefined") return body;
  return createPortal(body, document.body);
}
