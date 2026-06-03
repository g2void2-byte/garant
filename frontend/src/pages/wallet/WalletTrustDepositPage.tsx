import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ShieldCheck, ArrowUpFromLine, X } from "lucide-react";
import {
  useCreateWalletDeposit,
  useCurrencies,
  useMe,
  useAdmins,
} from "@/api/hooks";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { usePresence } from "@/lib/animate";
import { cn } from "@/lib/cn";
import { formatCurrency, formatMoney } from "@/lib/format";
import { haptic, openPaymentLink, openTelegramLink } from "@/lib/tg";

const DECIMAL_RE = /^\d+(?:\.\d{1,18})?$|^\.\d{1,18}$/;

/**
 * "Депозит доверия" page.
 * Displays trust balance and includes both "Внести депозит" and "Вывести депозит" buttons
 * in the trust deposit section.
 */
export default function WalletTrustDepositPage() {
  const currencies = useCurrencies();
  const me = useMe();
  const create = useCreateWalletDeposit();
  const toast = useToast();
  const { data: admins } = useAdmins();

  const [code, setCode] = useState<string>("");
  const [amount, setAmount] = useState<string>("");
  const [withdrawOpen, setWithdrawOpen] = useState(false);

  const current = useMemo(
    () => currencies.data?.find((c) => c.code === code),
    [currencies.data, code],
  );

  useEffect(() => {
    if (!code && currencies.data?.length) {
      setCode(currencies.data[0].code);
    }
  }, [code, currencies.data]);

  useEffect(() => {
    if (current && !amount) {
      setAmount(String(current.min_deposit));
    }
  }, [current, amount]);

  if (currencies.isLoading) {
    return (
      <Page showBack>
        <Header title="Депозит доверия" />
        <div className="px-4 space-y-2">
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-11 w-full rounded-button" />
        </div>
      </Page>
    );
  }

  async function submit() {
    if (!current) return;
    const value = amount.trim();
    if (!DECIMAL_RE.test(value) || /^0+(?:\.0+)?$/.test(value)) {
      haptic("error");
      toast.show({ kind: "error", title: "Введите корректную сумму" });
      return;
    }
    try {
      const dep = await create.mutateAsync({
        currency_code: current.code,
        amount: value,
        purpose: "trust",
      });
      haptic("success");
      if (dep.pay_url) openPaymentLink(dep.pay_url);
      toast.show({
        kind: "success",
        title: "Счёт создан",
        body: `Оплатите ${formatCurrency(dep.amount, dep.currency.code, current.decimals)} в CryptoBot.`,
      });
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось создать депозит",
      });
    }
  }

  const currencyOptions = (currencies.data ?? []).map((c) => ({
    value: c.code,
    label: `${c.name} (${c.network || c.code})`,
  }));
  const trustBalance = me.data?.deposit ?? 0;

  return (
    <Page showBack>
      <Header title="Депозит доверия" />
      <div className="px-4 space-y-3">
        <div className="bg-panel rounded-card p-4 space-y-1">
          <div className="text-xs text-text-muted">Текущий баланс</div>
          <div className="text-2xl font-semibold tabular-nums">
            {formatMoney(trustBalance)}
          </div>
        </div>

        {/* Action buttons inside the Trust Deposit section */}
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => {
              const input = document.querySelector('input[type="number"]');
              if (input) (input as HTMLInputElement).focus();
            }}
            className="flex items-center justify-center gap-2 h-11 rounded-button bg-panel border border-border text-text font-medium active:scale-[0.98] transition"
          >
            <ShieldCheck className="size-4 text-accent" />
            Внести депозит
          </button>
          <button
            type="button"
            onClick={() => setWithdrawOpen(true)}
            className="flex items-center justify-center gap-2 h-11 rounded-button bg-panel border border-border text-text font-medium active:scale-[0.98] transition"
          >
            <ArrowUpFromLine className="size-4 text-accent" />
            Вывести депозит
          </button>
        </div>

        <div className="border-t border-border/50 pt-3">
          <div className="mb-1 text-[14px] font-medium">Пополнение депозита</div>
          <div className="space-y-3">
            <div>
              <div className="mb-1 text-[12px] text-text-muted">Выберите валюту</div>
              <Select
                value={code}
                options={currencyOptions}
                onChange={setCode}
                withIcon={false}
                placeholder="Выберите валюту"
              />
            </div>
            <Input
              label="Сумма"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              type="number"
              inputMode="decimal"
              placeholder={current ? String(current.min_deposit) : "0"}
            />
            {current && (
              <div className="text-xs text-text-muted">
                Минимум: {formatCurrency(current.min_deposit, current.code, current.decimals)}
              </div>
            )}
            <Button
              fullWidth
              onClick={submit}
              disabled={create.isPending || !current}
            >
              <ShieldCheck className="size-4" />
              {create.isPending ? "Создаю счет..." : "Пополнить"}
            </Button>
          </div>
        </div>

        <p className="text-xs text-text-muted leading-relaxed pt-2">
          Депозит доверия — это лок-ин сумма, которая отображается у вас в
          профиле как подтверждение надёжности. Эти средства нельзя
          использовать в сделках. Для вывода депозита доверия воспользуйтесь кнопкой выше.
        </p>
      </div>

      <TrustWithdrawModal
        open={withdrawOpen}
        onClose={() => setWithdrawOpen(false)}
        admins={admins ?? []}
      />
    </Page>
  );
}

interface TrustWithdrawModalProps {
  open: boolean;
  onClose: () => void;
  admins: { username?: string | null }[];
}

function TrustWithdrawModal({ open, onClose, admins }: TrustWithdrawModalProps) {
  const { mounted, visible } = usePresence(open, 200);
  const adminUsername = admins?.[0]?.username;

  function writeAdmin() {
    haptic("light");
    if (adminUsername) {
      openTelegramLink(`https://t.me/${adminUsername}`);
    }
  }

  if (!mounted) return null;

  const body = (
    <div role="dialog" aria-modal="true" aria-labelledby="trust-withdraw-title">
      <div
        className={cn(
          "fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm transition-opacity duration-200",
          visible ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <div
        className={cn(
          "fixed inset-0 z-[61] grid place-items-center p-4 pointer-events-none",
          "transition-opacity duration-200",
          visible ? "opacity-100" : "opacity-0",
        )}
      >
        <div
          className={cn(
            "pointer-events-auto w-full max-w-sm rounded-3xl bg-panel border border-border shadow-pop p-6",
            "transform transition-all duration-200",
            visible ? "scale-100 opacity-100" : "scale-95 opacity-0",
          )}
        >
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3 min-w-0">
              <div className="size-11 grid place-items-center rounded-2xl bg-accent/15 text-accent shrink-0">
                <ShieldCheck className="size-5" />
              </div>
              <div className="min-w-0">
                <h2
                  id="trust-withdraw-title"
                  className="text-[18px] font-semibold tracking-tight text-text"
                >
                  Вывод депозита
                </h2>
                <p className="text-[12px] text-text-muted">Ручной возврат через администратора</p>
              </div>
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
          <p className="mt-4 text-[14px] text-text-muted leading-relaxed">
            Вывод депозита доверия осуществляется вручную администратором.
            Напишите администратору, указав сумму и реквизиты, и он осуществит возврат средств.
          </p>
          <div className="mt-5 grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-11 rounded-button bg-secondary text-text font-medium hover:opacity-90 active:opacity-80 transition"
            >
              Отмена
            </button>
            <Button
              size="md"
              onClick={writeAdmin}
              disabled={!adminUsername}
              className="!h-11"
            >
              Написать админу
            </Button>
          </div>
          {!adminUsername && (
            <p className="mt-3 text-[12px] text-danger">
              Контакт администратора пока недоступен. Попробуйте позже.
            </p>
          )}
        </div>
      </div>
    </div>
  );

  if (typeof document === "undefined") return body;
  return createPortal(body, document.body);
}
