import { Link, useNavigate } from "react-router-dom";
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ShieldCheck,
  Wallet as WalletIcon,
} from "lucide-react";
import { useMe, useWalletBalances } from "@/api/hooks";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { normalizeCurrencyCode, walletCurrencyPath } from "@/lib/currencyCodes";
import { formatMoney } from "@/lib/format";
import {
  formatWalletBalanceCurrency,
  hasPositiveWalletBalance,
} from "@/lib/walletAmounts";
import type { WalletBalanceDto } from "@/api/types";

/**
 * Continental "Депозит" page (photo 8 of 20).
 *
 * Layout:
 *   - Title "Депозит" (no subtitle).
 *   - List of currency rows, each: icon + name/network + balance.
 *   - Two action tiles at the bottom: "Внести депозит" / "Вывести депозит".
 *
 * Each currency row is a ``<Link>`` to ``/wallet/<code>`` so users can
 * drill into the per-currency deposit / withdraw / history page
 * (``WalletCurrencyPage``). The two action tiles at the bottom still
 * point at the multi-currency ``/wallet/deposit`` and
 * ``/wallet/withdraw`` aggregator flows.
 */
export default function WalletPage() {
  const navigate = useNavigate();
  // Item 15 — fetch only fiat balances. The backend filter keeps
  // crypto rows off the wire entirely; the client-side
  // ``b.currency.kind === 'fiat'`` guard below stays as a defensive
  // fallback for any in-flight cache entries written by an older
  // build (the cache key changed so this branch is mostly dead, but
  // cheap to keep).
  const { data, isLoading } = useWalletBalances({ kind: "fiat" });
  // ``UserCardDto.deposit`` is the **trust** deposit balance after
  // the country-deposit-filter refactor (see
  // ``backend/app/serializers.py:_common_user_fields``). It's a
  // single scalar (not per-currency) by design — trust deposits are
  // lock-in funds with no spend/withdraw path.
  const me = useMe();
  const trustBalance = me.data?.deposit ?? 0;

  return (
    <Page showBack>
      <Header title="Кошелёк" />
      <div className="px-4 space-y-2">
        {isLoading && (
          <>
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[64px] w-full rounded-card" />
            ))}
          </>
        )}
        {(() => {
          // Per the deposit-flow plan the wallet surfaces only the
          // fiat balances (UAH/RUB/USD) — crypto rows stay in the
          // ledger but are hidden from the user-facing list. ``kind``
          // is optional on the wire for backwards-compatibility, so
          // we default missing values to ``"crypto"`` (which gets
          // filtered out).
          const fiatBalances =
            data?.filter(
              (b) =>
                (b.currency.kind ?? "crypto") === "fiat" &&
                normalizeCurrencyCode(b.currency.code) !== null,
            ) ?? [];
          if (isLoading) return null;
          if (fiatBalances.length === 0) {
            return (
              <EmptyState
                icon={<WalletIcon className="size-8" />}
                title="Пока пусто"
                description="Пополните баланс через выбранную валюту, чтобы начать"
              />
            );
          }
          return fiatBalances.map((b) => (
            <WalletBalanceRow key={b.currency.id} balance={b} />
          ));
        })()}

        <div className="grid grid-cols-2 gap-2 pt-2">
          <button
            type="button"
            onClick={() => navigate("/wallet/deposit")}
            className="flex flex-col items-start gap-2 bg-panel rounded-card p-4 active:scale-[0.98] transition"
          >
            <ArrowDownToLine className="size-5 text-accent" />
            <div className="text-[15px] font-medium leading-tight text-left">
              Пополнить
              <br />
              баланс
            </div>
          </button>
          <button
            type="button"
            onClick={() => navigate("/wallet/withdraw")}
            className="flex flex-col items-start gap-2 bg-panel rounded-card p-4 active:scale-[0.98] transition"
          >
            <ArrowUpFromLine className="size-5 text-accent" />
            <div className="text-[15px] font-medium leading-tight text-left">
              Вывести
              <br />
              средства
            </div>
          </button>
        </div>

        <section className="pt-4 space-y-2">
          <h2 className="text-sm font-semibold text-text-muted px-1 flex items-center gap-2">
            <ShieldCheck className="size-4" /> Депозит доверия
          </h2>
          <div className="bg-panel rounded-card p-4 space-y-3">
            <div>
              <div className="text-xs text-text-muted">Текущий баланс</div>
              <div className="mt-1 text-2xl font-semibold tabular-nums">
                {formatMoney(trustBalance)}
              </div>
            </div>
            <p className="text-xs text-text-muted leading-relaxed">
              Депозит доверия — это деньги, которыми вы подтверждаете свою
              надёжность другим пользователям. Они отображаются у вас в
              профиле, но недоступны для оплаты сделок и вывода.
            </p>
            <button
              type="button"
              onClick={() => navigate("/wallet/trust-deposit")}
              className="w-full flex items-center justify-center gap-2 bg-accent text-accent-fg rounded-button px-4 py-2.5 font-semibold active:scale-[0.98] transition"
            >
              <ShieldCheck className="size-4" />
              Управление депозитом
            </button>
          </div>
        </section>
      </div>
    </Page>
  );
}

function WalletBalanceRow({ balance }: { balance: WalletBalanceDto }) {
  const { currency } = balance;
  const code = normalizeCurrencyCode(currency.code);
  const path = walletCurrencyPath(code);
  if (!code || !path) return null;
  return (
    <Link
      to={path}
      className="flex items-center justify-between bg-panel rounded-card p-3 active:scale-[0.98] transition"
      aria-label={`Открыть ${currency.name}`}
    >
      <div className="flex items-center gap-3">
        <div className="size-10 rounded-full bg-panel-2 grid place-items-center text-[13px] font-bold text-accent">
          {code.slice(0, 4)}
        </div>
        <div>
          <div className="font-semibold leading-tight">{currency.name}</div>
          <div className="text-xs text-text-muted leading-tight mt-0.5">
            {currency.network || code}
          </div>
        </div>
      </div>
      <div className="text-right">
        <div className="font-semibold tabular-nums">
          {formatWalletBalanceCurrency(balance, "amount", code, currency.decimals)}
        </div>
        {hasPositiveWalletBalance(balance, "locked") && (
          <div className="text-xs text-text-muted">
            +{formatWalletBalanceCurrency(balance, "locked", code, currency.decimals)} в заявках
          </div>
        )}
      </div>
    </Link>
  );
}
