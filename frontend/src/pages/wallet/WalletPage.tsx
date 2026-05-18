import { useNavigate } from "react-router-dom";
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
import { formatMoney } from "@/lib/format";
import { formatCurrency } from "@/lib/format";
import type { WalletBalanceDto } from "@/api/types";

/**
 * Continental "Депозит" page (photo 8 of 20).
 *
 * Layout:
 *   - Title "Депозит" (no subtitle).
 *   - List of currency rows, each: icon + name/network + balance.
 *   - Two action tiles at the bottom: "Внести депозит" / "Вывести депозит".
 *
 * Rows are *not* clickable; the in/out flows live on dedicated subpages
 * (`/wallet/deposit`, `/wallet/withdraw`) — same as Continental.
 */
export default function WalletPage() {
  const navigate = useNavigate();
  const { data, isLoading } = useWalletBalances();
  // ``UserCardDto.deposit`` is the **trust** deposit balance after
  // the country-deposit-filter refactor (see
  // ``backend/app/serializers.py:_common_user_fields``). It's a
  // single scalar (not per-currency) by design — trust deposits are
  // lock-in funds with no spend/withdraw path.
  const me = useMe();
  const trustBalance = me.data?.deposit ?? 0;

  return (
    <Page>
      <Header title="Депозит" />
      <div className="px-4 space-y-2">
        {isLoading && (
          <>
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[64px] w-full rounded-card" />
            ))}
          </>
        )}
        {!isLoading && !data?.length && (
          <EmptyState
            icon={<WalletIcon className="size-8" />}
            title="Пока пусто"
            description="Валюты появятся, как только администратор их добавит"
          />
        )}
        {!isLoading &&
          data?.map((b) => <WalletBalanceRow key={b.currency.id} balance={b} />)}

        <div className="grid grid-cols-2 gap-2 pt-2">
          <button
            type="button"
            onClick={() => navigate("/wallet/deposit")}
            className="flex flex-col items-start gap-2 bg-panel rounded-card p-4 active:scale-[0.98] transition"
          >
            <ArrowDownToLine className="size-5 text-accent" />
            <div className="text-[15px] font-medium leading-tight text-left">
              Внести
              <br />
              депозит
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
              депозит
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
              Внести депозит доверия
            </button>
          </div>
        </section>
      </div>
    </Page>
  );
}

function WalletBalanceRow({ balance }: { balance: WalletBalanceDto }) {
  const { currency, amount } = balance;
  return (
    <div className="flex items-center justify-between bg-panel rounded-card p-3">
      <div className="flex items-center gap-3">
        <div className="size-10 rounded-full bg-panel-2 grid place-items-center text-[13px] font-bold text-accent">
          {currency.code.slice(0, 4)}
        </div>
        <div>
          <div className="font-semibold leading-tight">{currency.name}</div>
          <div className="text-xs text-text-muted leading-tight mt-0.5">
            {currency.network || currency.code}
          </div>
        </div>
      </div>
      <div className="text-right">
        <div className="font-semibold tabular-nums">
          {formatCurrency(amount, currency.code, currency.decimals)}
        </div>
        {balance.locked > 0 && (
          <div className="text-xs text-text-muted">
            +{formatCurrency(balance.locked, currency.code, currency.decimals)} в заявках
          </div>
        )}
      </div>
    </div>
  );
}
