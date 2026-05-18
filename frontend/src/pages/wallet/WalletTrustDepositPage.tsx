import { useEffect, useMemo, useState } from "react";
import { ShieldCheck } from "lucide-react";
import {
  useCreateWalletDeposit,
  useCurrencies,
  useMe,
} from "@/api/hooks";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { formatCurrency, formatMoney } from "@/lib/format";
import { haptic, openTelegramLink } from "@/lib/tg";

/**
 * "Депозит доверия" top-up page.
 *
 * Mirrors ``WalletDepositPage``: currency picker, amount input,
 * "Внести депозит доверия" CTA that creates a CryptoBot invoice and
 * opens the pay URL. The only behavioural difference is the
 * ``purpose: "trust"`` flag on the create-deposit request — that
 * routes the credited funds to ``User.trust_deposit_balance``
 * (single-scalar, non-spendable, non-withdrawable) instead of the
 * per-currency ``UserBalance.amount``. See
 * ``backend/app/services_wallet.py:credit_deposit`` for the routing.
 *
 * The page intentionally has **no withdraw button** — trust deposits
 * are lock-in by design (audit §2.2). The only way the balance ever
 * moves is "incoming via this page" → "displayed in profile / wallet
 * page" forever.
 */
export default function WalletTrustDepositPage() {
  const currencies = useCurrencies();
  const me = useMe();
  const create = useCreateWalletDeposit();
  const toast = useToast();

  const [code, setCode] = useState<string>("");
  const [amount, setAmount] = useState<string>("");

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
    const value = parseFloat(amount);
    if (!Number.isFinite(value) || value <= 0) {
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
      if (dep.pay_url) openTelegramLink(dep.pay_url);
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
        <div>
          <div className="mb-1 text-[14px] font-medium">Выберите валюту</div>
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
          {create.isPending ? "Создаю депозит..." : "Внести депозит доверия"}
        </Button>
        <p className="text-xs text-text-muted leading-relaxed">
          Депозит доверия — это лок-ин сумма, которая отображается у вас в
          профиле как подтверждение надёжности. Эти средства нельзя
          использовать в сделках и вывести.
        </p>
      </div>
    </Page>
  );
}
