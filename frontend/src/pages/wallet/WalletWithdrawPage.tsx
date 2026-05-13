import { useEffect, useMemo, useState } from "react";
import { ArrowUpFromLine } from "lucide-react";
import {
  useCreateWalletWithdrawal,
  useWalletBalances,
} from "@/api/hooks";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { useToast } from "@/components/ui/Toast";
import { formatCurrency } from "@/lib/format";
import { haptic } from "@/lib/tg";

/**
 * Continental "Вывести депозит" page.
 *
 * Only currencies with a non-zero balance are offered. Submitting calls
 * the PIN-protected ``POST /api/wallet/withdrawals``; the UI prompts for
 * the PIN via the wrapped ``PinUser`` dependency.
 */
export default function WalletWithdrawPage() {
  const balances = useWalletBalances();
  const create = useCreateWalletWithdrawal();
  const toast = useToast();

  const [code, setCode] = useState<string>("");
  const [amount, setAmount] = useState<string>("");
  const [address, setAddress] = useState<string>("");

  const eligible = useMemo(
    () => (balances.data ?? []).filter((b) => b.amount > 0),
    [balances.data],
  );
  const current = useMemo(
    () => eligible.find((b) => b.currency.code === code),
    [eligible, code],
  );

  useEffect(() => {
    if (!code && eligible.length) {
      setCode(eligible[0].currency.code);
    }
  }, [code, eligible]);

  if (balances.isLoading) {
    return (
      <Page showBack>
        <Header title="Вывести депозит" />
        <div className="px-4 space-y-2">
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-12 w-full rounded-button" />
          <Skeleton className="h-11 w-full rounded-button" />
        </div>
      </Page>
    );
  }

  if (!eligible.length) {
    return (
      <Page showBack>
        <Header title="Вывести депозит" />
        <div className="px-4">
          <EmptyState
            title="У вас нет доступных для вывода валют"
            description="Пополните баланс через «Внести депозит», чтобы запросить вывод."
          />
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
    if (!address.trim()) {
      haptic("error");
      toast.show({ kind: "error", title: "Введите адрес кошелька" });
      return;
    }
    try {
      await create.mutateAsync({
        currency_code: current.currency.code,
        amount: value,
        address: address.trim(),
      });
      haptic("success");
      toast.show({
        kind: "success",
        title: "Заявка отправлена",
        body: "Администратор обработает её в ближайшее время.",
      });
      setAmount("");
      setAddress("");
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Ошибка при выводе средств",
      });
    }
  }

  const options = eligible.map((b) => ({
    value: b.currency.code,
    label: `${b.currency.name} · ${formatCurrency(b.amount, b.currency.code, b.currency.decimals)}`,
  }));

  return (
    <Page showBack>
      <Header title="Вывести депозит" />
      <div className="px-4 space-y-3">
        <div>
          <div className="mb-1 text-[14px] font-medium">Выберите валюту для вывода средств</div>
          <Select
            value={code}
            options={options}
            onChange={(v) => {
              setCode(v);
              setAmount("");
            }}
            withIcon={false}
          />
        </div>
        {current && (
          <div className="flex items-center justify-between text-xs text-text-muted">
            <span>
              Доступно:{" "}
              {formatCurrency(
                current.amount,
                current.currency.code,
                current.currency.decimals,
              )}
            </span>
            <button
              type="button"
              className="text-accent underline"
              onClick={() => setAmount(String(current.amount))}
            >
              Всё
            </button>
          </div>
        )}
        <Input
          label="Сумма"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          type="number"
          inputMode="decimal"
          placeholder={current ? String(current.currency.min_withdraw) : "0"}
        />
        <Input
          label="Адрес кошелька"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder={current ? `Адрес ${current.currency.code}` : "Адрес"}
        />
        <Button
          fullWidth
          onClick={submit}
          disabled={create.isPending || !current}
        >
          <ArrowUpFromLine className="size-4" />
          {create.isPending ? "Создаю заявку..." : "Запросить вывод"}
        </Button>
        <p className="text-xs text-text-muted leading-relaxed">
          Средства заблокированы на время вывода. Через 72 часа свяжитесь с поддержкой,
          если статус не изменится.
        </p>
      </div>
    </Page>
  );
}
