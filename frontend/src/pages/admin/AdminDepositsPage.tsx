import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowDownToLine,
  Check,
  ChevronLeft,
  ChevronRight,
  RefreshCcw,
} from "lucide-react";
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
import { formatDateTime } from "@/lib/format";
import { isSafeExternalLink, openPaymentLink } from "@/lib/tg";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";
import {
  formatAdminAmount,
  formatAdminCount,
  formatAdminCurrencyCode,
  formatAdminDepositStatus,
  formatAdminId,
  formatAdminUsername,
  getAdminTotalPages,
  hasPositiveAdminDecimal,
  parseAdminId,
} from "./format";

// Audit L-10 — ``null`` is the in-component sentinel for "all
// statuses"; the legacy ``"any"`` string is gone.
const DEPOSIT_STATUSES = ["pending", "paid", "refunded", "expired"] as const;
type DepositStatus = (typeof DEPOSIT_STATUSES)[number];
const STATUSES: Array<{ value: DepositStatus | null; label: string }> = [
  { value: null, label: "Все" },
  ...DEPOSIT_STATUSES.map((value) => ({ value, label: value })),
];
const PAGE_SIZE = 50;

export default function AdminDepositsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<DepositStatus | null>(null);
  const [page, setPage] = useState(1);
  const { data, isLoading } = useAdminDeposits({
    status: status ?? undefined,
    page,
    page_size: PAGE_SIZE,
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
        subtitle={data ? `${formatAdminCount(data.total)} всего` : undefined}
      />
      <div className="px-4 mb-3 flex flex-wrap gap-1.5">
        {STATUSES.map((s) => (
          <button
            key={s.value ?? "__none__"}
            type="button"
            onClick={() => {
              setStatus(s.value);
              setPage(1);
            }}
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
          data?.items.map((d, _idx) => {
            const depositId = parseAdminId(d.id);
            return (
            <div
              key={d.id}
              className="bg-panel rounded-card p-3"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="font-medium">
                    {formatAdminAmount(d.amount)} {formatAdminCurrencyCode(d.currency_code)}
                  </div>
                  <div className="text-xs text-text-muted truncate">
                    {formatAdminUsername(d.username)} ({d.display_name}) · #{formatAdminId(d.id)}
                  </div>
                  <div className="text-[11px] text-text-muted mt-1">
                    {formatDateTime(d.created_at)}
                  </div>
                </div>
                <StatusBadge status={d.status} />
              </div>
              <div className="mt-2 flex gap-2">
                {depositId !== null && d.status === "pending" && hasPositiveAdminDecimal(d.amount) && (
                  <Button
                    type="button"
                    size="sm"
                    onClick={async () => {
                      try {
                        await markPaid.mutateAsync({ id: depositId });
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
                {depositId !== null && d.status === "paid" && hasPositiveAdminDecimal(d.amount) && (
                  <Button
                    type="button"
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      try {
                        await refund.mutateAsync({ id: depositId });
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
                {hasPositiveAdminDecimal(d.amount) && d.pay_url && isSafeExternalLink(d.pay_url) && (
                  <button
                    type="button"
                    onClick={() => openPaymentLink(d.pay_url!)}
                    className="text-xs text-text-muted underline self-center"
                  >
                    <ArrowDownToLine size={12} className="inline mr-1" />
                    pay_url
                  </button>
                )}
              </div>
            </div>
            );
          })
        )}
      </div>
      {data && getAdminTotalPages(data.total, PAGE_SIZE) > 1 && (
        <Pagination
          page={page}
          totalPages={getAdminTotalPages(data.total, PAGE_SIZE)}
          onPage={setPage}
        />
      )}
    </Page>
  );
}

function Pagination({
  page,
  totalPages,
  onPage,
}: {
  page: number;
  totalPages: number;
  onPage: (page: number) => void;
}) {
  return (
    <div className="flex items-center justify-center gap-3 mt-1 mb-4 text-sm">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        className="p-2 rounded-button bg-panel disabled:opacity-40 active:scale-95"
        aria-label="Назад"
      >
        <ChevronLeft size={18} />
      </button>
      <span className="text-text-muted">
        {page} / {totalPages}
      </span>
      <button
        type="button"
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
        className="p-2 rounded-button bg-panel disabled:opacity-40 active:scale-95"
        aria-label="Вперёд"
      >
        <ChevronRight size={18} />
      </button>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const label = formatAdminDepositStatus(status);
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
      {label}
    </span>
  );
}
