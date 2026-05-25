import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowDownToLine, RefreshCcw, Check } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import {
  useAdminDepositMarkPaid,
  useAdminDepositRefund,
  useAdminDeposits,
} from "@/api/admin/hooks";
import { parseDecimal } from "@/lib/format";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

// Audit L-10 — ``null`` is the in-component sentinel for "all
// statuses"; the legacy ``"any"`` string is gone.
const DEPOSIT_STATUSES = ["pending", "paid", "refunded", "expired"] as const;
type DepositStatus = (typeof DEPOSIT_STATUSES)[number];
const STATUSES: Array<{ value: DepositStatus | null; label: string }> = [
  { value: null, label: "Все" },
  ...DEPOSIT_STATUSES.map((value) => ({ value, label: value })),
];

export default function AdminDepositsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<DepositStatus | null>(null);
  const { data, isLoading } = useAdminDeposits({
    status: status ?? undefined,
    page: 1,
    page_size: 50,
  });
  const markPaid = useAdminDepositMarkPaid();
  const refund = useAdminDepositRefund();
  const toast = useToast();

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader
        title="Депозиты"
        subtitle={data ? `${data.total} всего` : undefined}
      />
      <div className="px-4 mb-3 flex flex-wrap gap-1.5">
        {STATUSES.map((s) => (
          <button
            key={s.value ?? "__none__"}
            type="button"
            onClick={() => setStatus(s.value)}
            className={`rounded-button px-3 py-1.5 text-sm transition ${
              s.value === status
                ? "bg-accent text-accent-fg font-medium"
                : "bg-panel text-text-muted"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="px-4 space-y-2 pb-24">
        {isLoading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-card" />
          ))
        ) : data?.items.length === 0 ? (
          <p className="text-sm text-text-muted text-center py-12">
            Депозитов нет
          </p>
        ) : (
          data?.items.map((d, _idx) => (
            <div
              key={d.id}
              className="bg-panel rounded-card p-3"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="font-medium">
                    {parseDecimal(d.amount).toFixed(2)} {d.currency_code}
                  </div>
                  <div className="text-xs text-text-muted truncate">
                    @{d.username ?? "—"} ({d.display_name}) · #{d.id}
                  </div>
                  <div className="text-[11px] text-text-muted mt-1">
                    {new Date(d.created_at).toLocaleString()}
                  </div>
                </div>
                <StatusBadge status={d.status} />
              </div>
              <div className="mt-2 flex gap-2">
                {d.status === "pending" && (
                  <Button
                    type="button"
                    size="sm"
                    onClick={async () => {
                      try {
                        await markPaid.mutateAsync({ id: d.id });
                        toast.show({ kind: "success", title: "Зачислен" });
                      } catch (e) {
                        toast.show({
                          kind: "error",
                          title: "Ошибка",
                          body: (e as Error).message,
                        });
                      }
                    }}
                  >
                    <Check size={14} className="mr-1" /> Зачислить
                  </Button>
                )}
                {d.status === "paid" && (
                  <Button
                    type="button"
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      try {
                        await refund.mutateAsync({ id: d.id });
                        toast.show({ kind: "success", title: "Возвращён" });
                      } catch (e) {
                        toast.show({
                          kind: "error",
                          title: "Ошибка",
                          body: (e as Error).message,
                        });
                      }
                    }}
                  >
                    <RefreshCcw size={14} className="mr-1" /> Возврат
                  </Button>
                )}
                {d.pay_url && (
                  <a
                    href={d.pay_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-text-muted underline self-center"
                  >
                    <ArrowDownToLine size={12} className="inline mr-1" />
                    pay_url
                  </a>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </Page>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: "bg-warning/10 text-warning",
    paid: "bg-success/10 text-success",
    refunded: "bg-panel-2 text-text-muted",
    expired: "bg-danger/10 text-danger",
  };
  return (
    <span
      className={`text-[10px] uppercase font-semibold rounded-full px-2 py-0.5 ${
        map[status] ?? "bg-panel-2 text-text-muted"
      }`}
    >
      {status}
    </span>
  );
}
