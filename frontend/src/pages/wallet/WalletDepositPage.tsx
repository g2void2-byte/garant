import { useEffect, useMemo, useState } from "react";
import { ArrowDownToLine } from "lucide-react";
import {
  useCreateWalletDeposit,
  useCurrencies,
  useWalletBalances,
} from "@/api/hooks";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { formatCurrency } from "@/lib/format";
import { haptic, openTelegramLink } from "@/lib/tg";

/**
 * Continental "Пополнение депозита" page.
 *
 * Continental layout:
 *   - Currency picker (dropdown showing all active currencies).
 *   - Amount input (with min-deposit placeholder).
 *   - "Пополнить депозит" button — opens the CryptoBot invoice URL.
 *   - Helper text below: "Пополните баланс через выбранную сеть и валюту".
 */
export default function WalletDepositPage() {
  const currencies = useCurrencies();
  const balances = useWalletBalances();
  const create = useCreateWalletDeposit();
  const toast = useToast();

  const [code, setCode] = useState<string>("");
  const [amount, setAmount] = useState<string>("");

  const current = useMemo(
    () => currencies.data?.find((c) => c.code === code),
    [currencies.data, code],
  );
  const balance = useMemo(
    () => balances.data?.find((b) => b.currency.code === code),
    [balances.data, code],
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
        <Header title="Пополнение депозита" />
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
      const dep = await create.mutateAsync({ currency_code: current.code, amount: value });
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

  return (
    <Page showBack>
      <Header title="Пополнение депозита" />
      <div className="px-4 space-y-3">
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
            {(balance?.amount ?? 0) > 0 && (
              <>
                {" "}
                · Доступно:{" "}
                {formatCurrency(balance!.amount, current.code, current.decimals)}
              </>
            )}
          </div>
        )}
        <Button
          fullWidth
          onClick={submit}
          disabled={create.isPending || !current}
        >
          <ArrowDownToLine className="size-4" />
          {create.isPending ? "Создаю депозит..." : "Пополнить депозит"}
        </Button>
        <p className="text-xs text-text-muted leading-relaxed">
          Пополните баланс через выбранную сеть и валюту. Уведомления о пополнениях
          приходят автоматически.
        </p>
      </div>
    </Page>
  );
}
