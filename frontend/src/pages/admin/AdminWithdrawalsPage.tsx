import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ChevronLeft, ChevronRight, Copy, Send, X } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import {
  useAdminDecideWithdrawal,
  useAdminWithdrawals,
} from "@/api/admin/hooks";
import { formatDateTime } from "@/lib/format";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";
import { formatAdminAmount, formatAdminCurrencyCode, formatAdminUsername, getAdminTotalPages, hasPositiveAdminDecimal, parseAdminCount } from "./format";

const STATUSES = ["pending", "approved", "rejected", "sent"] as const;
type Status = (typeof STATUSES)[number];
const PAGE_SIZE = 50;

/**
 * `/admin/withdrawals` — admin queue for manual withdrawal review.
 *
 * Auto-mode (toggle in `/admin/settings`) sends approved withdrawals
 * via CryptoBot Transfer immediately and they land here already in
 * the ``sent`` bucket. With auto-mode off, every withdrawal sits in
 * ``pending`` until an admin clicks Approve / Reject / Mark-sent.
 */
export default function AdminWithdrawalsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<Status>("pending");
  const [page, setPage] = useState(1);
  const { data, isLoading } = useAdminWithdrawals({ status, page });
  const decide = useAdminDecideWithdrawal();
  const toast = useToast();

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  const counters = data?.counters ?? {};
  const totalPages = getAdminTotalPages(counters[status], PAGE_SIZE);

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader title="Выводы" subtitle="Заявки на вывод" />
      <div className="px-4 mb-3 flex gap-1.5 overflow-x-auto">
        {STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => {
              setStatus(s);
              setPage(1);
            }}
            className={`relative rounded-button px-3 py-1.5 text-sm transition shrink-0 ${
              s === status
                ? "bg-accent text-accent-fg font-medium"
                : "bg-panel text-text-muted"
            }`}
          >
            {labelOf(s)}
            {(() => {
              const count = parseAdminCount(counters[s]);
              return count !== null && count > 0 ? (
              <span
                className={`ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full ${
                  s === status ? "bg-accent-fg/20" : "bg-panel-2 text-text"
                }`}
              >
                {count}
              </span>
              ) : null;
            })()}
          </button>
        ))}
      </div>
      <div className="px-4 space-y-2 pb-24">
        {isLoading ? (
          Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-card" />
          ))
        ) : data?.items.length === 0 ? (
          <p className="text-sm text-text-muted text-center py-12">
            Заявок нет
          </p>
        ) : (
          data?.items.map((w, _idx) => (
            <div
              key={w.id}
              className="bg-panel rounded-card p-3 space-y-2"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="font-medium">
                    {formatAdminAmount(w.amount, 8)} {formatAdminCurrencyCode(w.currency_code)}
                  </div>
                  <div className="text-xs text-text-muted">
                    {formatAdminUsername(w.username)} ({w.display_name}) · #{w.id}
                  </div>
                  <div className="text-[11px] text-text-muted">
                    {formatDateTime(w.created_at)}
                  </div>
                </div>
              </div>
              <div className="bg-panel-2 rounded-button px-2 py-1.5 flex items-center gap-1.5">
                <span className="text-[11px] text-text-muted">
                  {w.address ? "Адрес:" : "Получатель:"}
                </span>
                <code className="text-xs flex-1 truncate font-mono">
                  {w.address ?? "CryptoBot Transfer"}
                </code>
                {w.address && (
                  <button
                    type="button"
                    onClick={() => {
                      navigator.clipboard.writeText(w.address ?? "");
                      toast.show({ kind: "info", title: "Скопировано" });
                    }}
                    className="text-text-muted active:scale-90"
                  >
                    <Copy size={14} />
                  </button>
                )}
              </div>
              {w.admin_note && (
                <div className="text-xs text-text-muted italic">
                  Комментарий: {w.admin_note}
                </div>
              )}
              {status === "pending" && (
                <div className="flex gap-2 pt-1">
                  {hasPositiveAdminDecimal(w.amount) && (
                    <Button
                      type="button"
                      size="sm"
                      onClick={async () => {
                        try {
                          await decide.mutateAsync({
                            id: w.id,
                            body: { action: "approve" },
                          });
                          toast.show({
                            kind: "success",
                            title: "Одобрено",
                            body: "Если включён авто-режим, отправлено через CryptoBot",
                          });
                        } catch (e) {
                          toast.show({
                            kind: "error",
                            title: "Ошибка",
                            body: (e as Error).message,
                          });
                        }
                      }}
                    >
                      <Check size={14} className="mr-1" /> Одобрить
                    </Button>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      // Audit L-15 — Telegram WebApp has no native
                      // text-input prompt (``showConfirm`` is boolean,
                      // ``showPopup`` only takes fixed buttons), so
                      // ``window.prompt`` remains the least-bad option
                      // here. A future iteration can replace this with
                      // a Sheet-driven modal carrying a text input.
                      const note = window.prompt("Причина отказа (необязательно)") ?? "";
                      try {
                        await decide.mutateAsync({
                          id: w.id,
                          body: { action: "reject", note: note.trim() || undefined },
                        });
                        toast.show({ kind: "info", title: "Отклонено" });
                      } catch (e) {
                        toast.show({
                          kind: "error",
                          title: "Ошибка",
                          body: (e as Error).message,
                        });
                      }
                    }}
                  >
                    <X size={14} className="mr-1" /> Отклонить
                  </Button>
                </div>
              )}
              {status === "approved" && hasPositiveAdminDecimal(w.amount) && (
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={async () => {
                    try {
                      await decide.mutateAsync({
                        id: w.id,
                        body: { action: "mark_sent" },
                      });
                      toast.show({ kind: "success", title: "Отмечено как отправлено" });
                    } catch (e) {
                      toast.show({
                        kind: "error",
                        title: "Ошибка",
                        body: (e as Error).message,
                      });
                    }
                  }}
                >
                  <Send size={14} className="mr-1" /> Отмечено отправлено
                </Button>
              )}
            </div>
          ))
        )}
      </div>
      {totalPages > 1 && (
        <Pagination
          page={page}
          totalPages={totalPages}
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

function labelOf(s: Status): string {
  return {
    pending: "Ожидают",
    approved: "Одобренные",
    rejected: "Отклонённые",
    sent: "Отправленные",
  }[s];
}
