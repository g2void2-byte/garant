import { ArrowDownToLine, ArrowUpFromLine, Wallet } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { UserCardDto } from "@/api/types";
import { useWalletBalances } from "@/api/hooks";
import { formatCurrency } from "@/lib/format";
import { Skeleton } from "@/components/ui/Skeleton";

/**
 * Item 13 — ProfilePage fiat-balance card.
 *
 * The pre-fix profile only surfaced the *trust* deposit (lock-in,
 * scalar, ``UserCardDto.deposit``) — the per-currency fiat wallet
 * balance lived on ``WalletPage`` and was invisible from the user's
 * landing screen. When an admin credited a user's fiat balance via
 * ``/api/admin/wallets/<id>/adjust`` the user couldn't see the change
 * unless they navigated to ``/wallet`` first.
 *
 * This card renders the balance in the user's chosen
 * ``display_currency_code`` (falls back to USD) and exposes the
 * standard top-up / withdraw CTAs so the deposit/withdraw flows are
 * reachable in one tap from the profile.
 */
export function ProfileFiatBalanceCard({ user }: { user: UserCardDto }) {
  const navigate = useNavigate();
  // Item 15 — fetch the fiat-only slice; the historical crypto rows
  // stay in the ledger but the user-facing surfaces never see them.
  const { data, isLoading } = useWalletBalances({ kind: "fiat" });
  const code = user.display_currency_code || "USD";
  const balance = data?.find((b) => b.currency.code === code);
  const decimals = balance?.currency.decimals ?? 2;
  const amount = balance?.amount_str ?? "0";

  return (
    <section className="bg-panel border border-border rounded-card p-4 space-y-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-text-muted">
        <Wallet className="size-4" />
        Баланс ({code})
      </div>
      <div>
        {isLoading ? (
          <Skeleton className="h-8 w-32 rounded-button" />
        ) : (
          <div className="text-3xl font-bold text-accent tabular-nums">
            {formatCurrency(amount, code, decimals)}
          </div>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => navigate(`/wallet/deposit?currency=${code}`)}
          className="flex items-center justify-center gap-2 bg-panel-2 rounded-button px-3 py-2 text-sm font-medium active:scale-[0.98] transition"
        >
          <ArrowDownToLine className="size-4 text-accent" />
          Пополнить
        </button>
        <button
          type="button"
          onClick={() => navigate(`/wallet/withdraw?currency=${code}`)}
          className="flex items-center justify-center gap-2 bg-panel-2 rounded-button px-3 py-2 text-sm font-medium active:scale-[0.98] transition"
        >
          <ArrowUpFromLine className="size-4 text-accent" />
          Вывести
        </button>
      </div>
    </section>
  );
}
