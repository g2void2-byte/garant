import { Link } from "react-router-dom";
import { ChevronRight, Wallet as WalletIcon } from "lucide-react";
import { useWalletBalances } from "@/api/hooks";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { formatCurrency } from "@/lib/format";

export default function WalletPage() {
  const { data, isLoading } = useWalletBalances();

  return (
    <Page>
      <Header title="Кошелёк" subtitle="Балансы по валютам" />
      <div className="px-4 space-y-2">
        {isLoading && (
          <>
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-[68px] w-full rounded-card" />
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
          data?.map((b) => {
            const total = b.amount + b.locked;
            return (
              <Link
                key={b.currency.id}
                to={`/wallet/${b.currency.code}`}
                className="flex items-center justify-between bg-panel border border-border rounded-card p-4 hover:bg-panel-2 transition"
              >
                <div className="flex items-center gap-3">
                  <div className="size-10 rounded-full bg-panel-2 grid place-items-center text-sm font-semibold">
                    {b.currency.code}
                  </div>
                  <div>
                    <div className="font-semibold">{b.currency.name}</div>
                    <div className="text-xs text-text-muted">
                      {b.currency.network || b.currency.code}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="text-right">
                    <div className="font-semibold">
                      {formatCurrency(total, b.currency.code, b.currency.decimals)}
                    </div>
                    {b.locked > 0 && (
                      <div className="text-xs text-text-muted">
                        {formatCurrency(b.locked, b.currency.code, b.currency.decimals)} в заявках
                      </div>
                    )}
                  </div>
                  <ChevronRight className="size-5 text-text-muted" />
                </div>
              </Link>
            );
          })}
      </div>
    </Page>
  );
}
