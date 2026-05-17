import { useParams, useNavigate } from "react-router-dom";
import { CheckCircle2, Copy, Wallet } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { useToast } from "@/components/ui/Toast";
import { useDeal, useWalletBalances } from "@/api/hooks";
import { formatCurrency } from "@/lib/format";
import { haptic } from "@/lib/tg";

/**
 * Continental "Оплата сделки" page.
 *
 * Reached via the "Оплатить" CTA on a deal in ``pending_payment`` status.
 * Shows:
 *   - Amount due in the deal's currency.
 *   - The platform's deposit instructions (currency, network, balance).
 *   - "Оплатить" primary button that confirms payment via the
 *     wallet balance (the deal then auto-flips to ``in_progress``).
 *
 * If the user lacks balance, the action falls back to "Внести депозит".
 */
export default function DealPaymentPage() {
  const { id } = useParams<{ id: string }>();
  const dealId = Number(id);
  const navigate = useNavigate();
  const toast = useToast();
  const { data: deal, isLoading } = useDeal(Number.isFinite(dealId) ? dealId : undefined);
  const balances = useWalletBalances();

  if (isLoading || !deal) {
    return (
      <Page showBack>
        <Header title="Оплата сделки" />
        <div className="px-4 space-y-2">
          <Skeleton className="h-32 w-full rounded-card" />
          <Skeleton className="h-16 w-full rounded-card" />
          <Skeleton className="h-11 w-full rounded-button" />
        </div>
      </Page>
    );
  }

  if (deal.status !== "pending_payment") {
    return (
      <Page showBack>
        <Header title="Оплата сделки" />
        <div className="px-4">
          <EmptyState
            title="Сделка не требует оплаты"
            description={`Текущий статус: ${deal.status}. Оплата возможна только для сделок в статусе «Ожидает оплаты».`}
          />
        </div>
      </Page>
    );
  }

  const code = deal.currency_code || "USDT";
  const amount = deal.amount;
  const balance = balances.data?.find((b) => b.currency.code === code);
  const available = balance?.amount ?? 0;
  const decimals = balance?.currency.decimals ?? 2;
  const enough = available >= amount;

  const copyAmount = async () => {
    try {
      await navigator.clipboard.writeText(String(amount));
      haptic("light");
      toast.show({ kind: "success", title: "Сумма скопирована" });
    } catch {
      /* clipboard may be unavailable in TMA */
    }
  };

  return (
    <Page showBack>
      <Header title="Оплата сделки" />
      <div className="px-4 space-y-3">
        <div className="bg-panel rounded-card p-4 text-center">
          <div className="text-sm text-text-muted">Сумма к оплате</div>
          <div className="mt-2 text-3xl font-bold text-accent tabular-nums">
            {formatCurrency(amount, code, decimals)}
          </div>
          <div className="mt-1 text-xs text-text-muted">
            Сделка #{deal.id} · @{deal.role === "buyer" ? deal.seller : deal.buyer}
          </div>
          <button
            type="button"
            onClick={copyAmount}
            className="mt-3 inline-flex items-center gap-1.5 text-xs text-text-muted hover:text-accent"
          >
            <Copy className="size-3" /> Скопировать сумму
          </button>
        </div>

        <div className="bg-panel rounded-card p-4 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-text-muted">Баланс {code}</span>
            <span className="font-semibold tabular-nums">
              {formatCurrency(available, code, decimals)}
            </span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-text-muted">Статус оплаты:</span>
            <span className={enough ? "text-success font-semibold" : "text-danger font-semibold"}>
              {enough ? "достаточно средств" : "недостаточно средств"}
            </span>
          </div>
        </div>

        {enough ? (
          <div className="bg-panel rounded-card p-4 flex items-start gap-3">
            <CheckCircle2 className="size-5 text-success shrink-0 mt-0.5" />
            <div className="text-xs text-text-muted leading-relaxed">
              Подтвердите оплату — сумма будет списана с вашего баланса и заморожена
              до подтверждения сделки. Ожидайте подтверждения.
            </div>
          </div>
        ) : (
          <Button
            fullWidth
            variant="secondary"
            onClick={() => navigate("/wallet/deposit")}
          >
            <Wallet className="size-4" /> Внести депозит
          </Button>
        )}

        <Button
          fullWidth
          disabled={!enough}
          onClick={() => navigate(`/deals/${deal.id}`)}
        >
          Оплатить
        </Button>

        <p className="text-xs text-text-muted leading-relaxed">
          Депозит не служит для оплаты сделок. Используйте баланс, пополнив его через
          раздел «Внести депозит».
        </p>
      </div>
    </Page>
  );
}
