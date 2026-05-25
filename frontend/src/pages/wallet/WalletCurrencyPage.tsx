import { useMemo, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { ArrowDownToLine, ArrowUpFromLine, History } from "lucide-react";
import {
  useCreateWalletDeposit,
  useCreateWalletWithdrawal,
  useCurrencies,
  useWalletBalances,
  useWalletDeposits,
  useWalletWithdrawals,
} from "@/api/hooks";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { useToast } from "@/components/ui/Toast";
import { formatCurrency, relativeTime } from "@/lib/format";
import { haptic, openTelegramLink } from "@/lib/tg";

type Tab = "deposit" | "withdraw" | "history";

const DEPOSIT_STATUS_TEXT: Record<string, string> = {
  pending: "Ожидание",
  paid: "Зачислено",
  expired: "Истёк",
};

const WITHDRAW_STATUS_TEXT: Record<string, string> = {
  pending: "В очереди",
  approved: "Одобрена",
  sent: "Отправлено",
  rejected: "Отклонена",
};

const STATUS_TONE: Record<string, string> = {
  pending: "text-warning",
  paid: "text-success",
  expired: "text-text-muted",
  approved: "text-success",
  sent: "text-success",
  rejected: "text-danger",
};

export default function WalletCurrencyPage() {
  const { code = "" } = useParams<{ code: string }>();
  const upper = code.toUpperCase();

  const currencies = useCurrencies();
  const balances = useWalletBalances();
  const deposits = useWalletDeposits();
  const withdrawals = useWalletWithdrawals();

  const currency = useMemo(
    () => currencies.data?.find((c) => c.code === upper),
    [currencies.data, upper],
  );
  const balance = useMemo(
    () => balances.data?.find((b) => b.currency.code === upper),
    [balances.data, upper],
  );

  const [tab, setTab] = useState<Tab>("deposit");

  if (currencies.isLoading || balances.isLoading) {
    return (
      <Page showBack>
        <Header title={upper} />
        <div className="px-4 space-y-2">
          <Skeleton className="h-24 w-full rounded-card" />
          <Skeleton className="h-12 w-full rounded-2xl" />
          <Skeleton className="h-40 w-full rounded-card" />
        </div>
      </Page>
    );
  }

  if (!currency) {
    return (
      <Page showBack>
        <Header title={upper} />
        <div className="px-4 text-text-muted text-sm">Валюта не поддерживается.</div>
      </Page>
    );
  }

  // Item 15 — the user-facing wallet flow no longer surfaces crypto
  // codes; routes like ``/wallet/USDT`` deep-linked from bookmarks /
  // old DMs should bounce back to the wallet landing page instead of
  // rendering a crypto-only sub-page that the rest of the UI can't
  // reach.
  if ((currency.kind ?? "crypto") !== "fiat") {
    return <Navigate to="/wallet" replace />;
  }

  return (
    <Page showBack>
      <Header title={currency.name} subtitle={currency.network || currency.code} />
      <div className="px-4 space-y-3">
        <div className="bg-panel border border-border rounded-card p-4">
          <div className="text-sm text-text-muted">Доступно</div>
          <div className="mt-1 text-3xl font-bold text-accent">
            {formatCurrency(balance?.amount ?? 0, currency.code, currency.decimals)}
          </div>
          {(balance?.locked ?? 0) > 0 && (
            <div className="text-xs text-text-muted mt-1">
              в заявках: {formatCurrency(balance!.locked, currency.code, currency.decimals)}
            </div>
          )}
        </div>

        <ToggleTabs<Tab>
          value={tab}
          onChange={setTab}
          options={[
            { value: "deposit", label: "Пополнить", icon: <ArrowDownToLine className="size-4" /> },
            { value: "withdraw", label: "Вывести", icon: <ArrowUpFromLine className="size-4" /> },
            { value: "history", label: "История", icon: <History className="size-4" /> },
          ]}
        />

        {tab === "deposit" && (
          <DepositForm currencyCode={currency.code} minDeposit={currency.min_deposit} decimals={currency.decimals} />
        )}
        {tab === "withdraw" && (
          <WithdrawForm
            currencyCode={currency.code}
            minWithdraw={currency.min_withdraw}
            decimals={currency.decimals}
            available={balance?.amount ?? 0}
            availableStr={balance?.amount_str ?? "0"}
          />
        )}
        {tab === "history" && (
          <HistoryList
            currencyCode={currency.code}
            decimals={currency.decimals}
            depositsLoading={deposits.isLoading || withdrawals.isLoading}
            deposits={deposits.data?.filter((d) => d.currency.code === currency.code) ?? []}
            withdrawals={
              withdrawals.data?.filter((w) => w.currency.code === currency.code) ?? []
            }
          />
        )}
      </div>
    </Page>
  );
}

function DepositForm({
  currencyCode,
  minDeposit,
  decimals,
}: {
  currencyCode: string;
  minDeposit: number;
  decimals: number;
}) {
  const create = useCreateWalletDeposit();
  const toast = useToast();
  const [amount, setAmount] = useState(String(minDeposit));

  async function submit() {
    const value = parseFloat(amount);
    if (!Number.isFinite(value) || value <= 0) {
      haptic("error");
      toast.show({ kind: "error", title: "Введите корректную сумму" });
      return;
    }
    try {
      const dep = await create.mutateAsync({ currency_code: currencyCode, amount: value });
      haptic("success");
      if (dep.pay_url) openTelegramLink(dep.pay_url);
      toast.show({
        kind: "success",
        title: "Счёт создан",
        body: `Оплатите ${formatCurrency(dep.amount, dep.currency.code, decimals)} в CryptoBot.`,
      });
    } catch (e: unknown) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error)?.message || "Не удалось создать счёт" });
    }
  }

  return (
    <div className="bg-panel border border-border rounded-card p-4 space-y-3">
      <div className="text-sm text-text-muted">
        Минимум: {formatCurrency(minDeposit, currencyCode, decimals)}
      </div>
      <Input
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        type="number"
        inputMode="decimal"
        placeholder={String(minDeposit)}
      />
      <Button fullWidth onClick={submit} disabled={create.isPending}>
        {create.isPending ? "Создаю счёт..." : `Пополнить через CryptoBot`}
      </Button>
      <p className="text-xs text-text-muted">
        Оплата проходит в боте @CryptoBot. После оплаты средства поступят на ваш баланс автоматически.
      </p>
    </div>
  );
}

// Audit M-7 — see ``WalletWithdrawPage.tsx`` for the full rationale.
// Reject anything that isn't a well-formed decimal so we never round-trip
// through ``parseFloat``.
const _DECIMAL_RE = /^\d+(?:\.\d{1,18})?$|^\.\d{1,18}$/;

function WithdrawForm({
  currencyCode,
  minWithdraw,
  decimals,
  available,
  availableStr,
}: {
  currencyCode: string;
  minWithdraw: number;
  decimals: number;
  available: number;
  availableStr: string;
}) {
  const create = useCreateWalletWithdrawal();
  const toast = useToast();
  const [amount, setAmount] = useState("");
  const [address, setAddress] = useState("");

  async function submit() {
    const trimmed = amount.trim();
    if (!_DECIMAL_RE.test(trimmed) || /^0+(?:\.0+)?$/.test(trimmed)) {
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
      // Audit M-7 — send the user-visible decimal string straight to
      // the backend; ``WalletWithdrawCreateReq.amount: Decimal``
      // accepts it without ``float`` truncation.
      await create.mutateAsync({ currency_code: currencyCode, amount: trimmed, address });
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
      toast.show({ kind: "error", title: (e as Error)?.message || "Не удалось создать заявку" });
    }
  }

  return (
    <div className="bg-panel border border-border rounded-card p-4 space-y-3">
      <div className="flex items-center justify-between text-sm text-text-muted">
        <span>Доступно: {formatCurrency(available, currencyCode, decimals)}</span>
        <button
          type="button"
          onClick={() => setAmount(availableStr)}
          className="text-accent text-xs underline"
          disabled={available <= 0}
        >
          Всё
        </button>
      </div>
      <Input
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        type="number"
        inputMode="decimal"
        placeholder={`Минимум ${minWithdraw}`}
      />
      <Input
        value={address}
        onChange={(e) => setAddress(e.target.value)}
        placeholder={`Адрес ${currencyCode}`}
      />
      <Button fullWidth onClick={submit} disabled={create.isPending || available <= 0}>
        {create.isPending ? "Создаю заявку..." : "Запросить вывод"}
      </Button>
      <p className="text-xs text-text-muted">
        Заявки обрабатываются администратором вручную. До подтверждения сумма блокируется на балансе.
      </p>
    </div>
  );
}

function HistoryList({
  currencyCode,
  decimals,
  depositsLoading,
  deposits,
  withdrawals,
}: {
  currencyCode: string;
  decimals: number;
  depositsLoading: boolean;
  deposits: {
    id: number;
    amount: number;
    status: string;
    created_at: string;
    pay_url: string;
    provider: string;
  }[];
  withdrawals: {
    id: number;
    amount: number;
    address: string;
    status: string;
    created_at: string;
    admin_note: string;
  }[];
}) {
  type Row = {
    key: string;
    kind: "deposit" | "withdraw";
    title: string;
    subtitle: string;
    amount: number;
    sign: 1 | -1;
    status: string;
    created_at: string;
    pay_url?: string;
    provider?: string;
  };

  const rows: Row[] = [
    ...deposits.map<Row>((d) => ({
      key: `d-${d.id}`,
      kind: "deposit",
      title: "Пополнение",
      subtitle: DEPOSIT_STATUS_TEXT[d.status] ?? d.status,
      amount: d.amount,
      sign: 1,
      status: d.status,
      created_at: d.created_at,
      pay_url: d.status === "pending" ? d.pay_url : undefined,
      provider: d.provider,
    })),
    ...withdrawals.map<Row>((w) => ({
      key: `w-${w.id}`,
      kind: "withdraw",
      title: "Вывод",
      subtitle: [WITHDRAW_STATUS_TEXT[w.status] ?? w.status, w.admin_note]
        .filter(Boolean)
        .join(" · "),
      amount: w.amount,
      sign: -1,
      status: w.status,
      created_at: w.created_at,
    })),
  ].sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));

  if (depositsLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-16 w-full rounded-card" />
        <Skeleton className="h-16 w-full rounded-card" />
      </div>
    );
  }

  if (!rows.length) {
    return (
      <div className="bg-panel border border-border rounded-card p-6 text-center text-text-muted text-sm">
        Операций пока нет
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.key} className="bg-panel border border-border rounded-card p-3 flex items-center justify-between">
          <div className="min-w-0">
            <div className="font-semibold truncate flex items-center gap-2">
              <span>{r.title}</span>
              {r.kind === "deposit" && r.provider && (
                <span
                  className="inline-flex items-center rounded-full border border-border bg-bg px-2 py-[1px] text-[10px] font-medium uppercase text-text-muted"
                  data-testid={`deposit-provider-${r.provider}`}
                >
                  {r.provider === "crystalpay" ? "Crystalpay" : "CryptoBot"}
                </span>
              )}
            </div>
            <div className={`text-xs ${STATUS_TONE[r.status] ?? "text-text-muted"}`}>
              {r.subtitle}
            </div>
            <div className="text-[11px] text-text-muted mt-0.5">
              {relativeTime(r.created_at)}
            </div>
          </div>
          <div className="text-right">
            <div className={`font-semibold ${r.sign === 1 ? "text-success" : "text-text"}`}>
              {r.sign === 1 ? "+" : "-"}
              {formatCurrency(r.amount, currencyCode, decimals)}
            </div>
            {r.pay_url && (
              <Link
                to="#"
                onClick={(e) => {
                  e.preventDefault();
                  openTelegramLink(r.pay_url!);
                }}
                className="text-accent text-xs underline"
              >
                Оплатить
              </Link>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
