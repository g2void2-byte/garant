import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowDownToLine, CheckCircle2, ExternalLink, Wallet } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { useToast } from "@/components/ui/Toast";
import {
  useCreateDepositInvoice,
  useDeposits,
  useInvoiceStatus,
  useMe,
} from "@/api/hooks";
import { formatMoney, relativeTime } from "@/lib/format";
import { haptic, openTelegramLink } from "@/lib/tg";

const PRESETS = [10, 50, 100, 500];

const STATUS_TEXT: Record<string, string> = {
  active: "Активный",
  paid: "Оплачен",
  expired: "Истёк",
};

export default function DepositPage() {
  const { data: me } = useMe();
  const { data: deposits, isLoading } = useDeposits();
  const createInvoice = useCreateDepositInvoice();
  const toast = useToast();
  const qc = useQueryClient();

  const [amount, setAmount] = useState("50");
  const [activeInvoice, setActiveInvoice] = useState<{
    invoice_id: string;
    pay_url: string;
    amount: number;
  } | null>(null);

  const status = useInvoiceStatus(activeInvoice?.invoice_id ?? null, !!activeInvoice);

  useEffect(() => {
    if (!activeInvoice || !status.data) return;
    if (status.data.status === "paid" && status.data.credited) {
      haptic("success");
      toast.show({
        kind: "success",
        title: "Баланс пополнен",
        body: `На баланс зачислено ${formatMoney(status.data.paid_amount)}`,
      });
      qc.invalidateQueries({ queryKey: ["me"] });
      qc.invalidateQueries({ queryKey: ["payments"] });
      setActiveInvoice(null);
    } else if (status.data.status === "expired") {
      toast.show({ kind: "error", title: "Счёт истёк" });
      setActiveInvoice(null);
    }
  }, [status.data, activeInvoice, qc, toast]);

  const handleCreate = async () => {
    const value = parseFloat(amount);
    if (!Number.isFinite(value) || value <= 0) {
      haptic("error");
      toast.show({ kind: "error", title: "Введите корректную сумму" });
      return;
    }
    try {
      const invoice = await createInvoice.mutateAsync(value);
      haptic("success");
      if (!invoice.invoice_id || !invoice.pay_url) {
        toast.show({ kind: "error", title: "CryptoBot не вернул ссылку на оплату" });
        return;
      }
      setActiveInvoice({
        invoice_id: String(invoice.invoice_id),
        pay_url: invoice.pay_url,
        amount: value,
      });
      openTelegramLink(invoice.pay_url);
    } catch (e: unknown) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error)?.message || "Не удалось создать счёт" });
    }
  };

  return (
    <Page showBack>
      <Header title="Пополнение баланса" subtitle="USDT через CryptoBot" />
      <div className="px-4 space-y-3">
        <div className="bg-panel border border-border rounded-card p-4">
          <div className="text-sm text-text-muted">Текущий баланс</div>
          <div className="mt-1 text-3xl font-bold text-accent">{formatMoney(me?.balance ?? 0)}</div>
        </div>

        <div className="bg-panel border border-border rounded-card p-4 space-y-3">
          <div className="text-sm text-text-muted">Сумма пополнения</div>
          <Input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            type="number"
            min={1}
            placeholder="50"
          />
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <Button
                key={p}
                size="sm"
                variant="ghost"
                onClick={() => setAmount(String(p))}
                className="bg-panel-2"
              >
                {p} USDT
              </Button>
            ))}
          </div>
          <Button
            fullWidth
            onClick={handleCreate}
            disabled={createInvoice.isPending || !!activeInvoice}
          >
            <Wallet className="size-4" />
            {createInvoice.isPending ? "Создаю счёт..." : "Пополнить через CryptoBot"}
          </Button>
        </div>

        {activeInvoice && (
          <div className="bg-panel border border-accent/40 rounded-card p-4 space-y-2">
            <div className="flex items-center gap-2 text-accent">
              <CheckCircle2 className="size-5" />
              <div className="font-semibold">Счёт создан</div>
            </div>
            <div className="text-sm text-text-muted">
              Оплатите счёт на {formatMoney(activeInvoice.amount)}. Баланс обновится автоматически после оплаты.
            </div>
            <div className="text-xs text-text-muted">
              Статус: <span className="font-semibold">{STATUS_TEXT[status.data?.status ?? ""] ?? status.data?.status ?? "проверяем..."}</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button
                variant="secondary"
                onClick={() => openTelegramLink(activeInvoice.pay_url)}
              >
                <ExternalLink className="size-4" /> Открыть оплату
              </Button>
              <Button
                variant="ghost"
                onClick={() => status.refetch()}
                disabled={status.isFetching}
              >
                {status.isFetching ? "Проверяю..." : "Проверить сейчас"}
              </Button>
            </div>
          </div>
        )}

        <div>
          <div className="text-sm text-text-muted px-1 pb-2 uppercase tracking-wide">История депозитов</div>
          {isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : !deposits || deposits.length === 0 ? (
            <EmptyState
              icon={<ArrowDownToLine className="size-5" />}
              title="Пока пусто"
              description="История появится после первого пополнения"
            />
          ) : (
            <div className="space-y-2">
              {deposits.map((d) => (
                <div key={d.id} className="bg-panel border border-border rounded-card p-3 flex items-center justify-between">
                  <div>
                    <div className="font-semibold">{formatMoney(d.amount)}</div>
                    <div className="text-xs text-text-muted">{relativeTime(d.created_at)}</div>
                  </div>
                  <div className="text-xs uppercase tracking-wide text-text-muted">{STATUS_TEXT[d.status] ?? d.status}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Page>
  );
}
