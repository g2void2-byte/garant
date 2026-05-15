import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, X, Send, Copy } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import {
  useAdminDecideWithdrawal,
  useAdminWithdrawals,
} from "@/api/admin/hooks";
import { parseDecimal } from "@/lib/format";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

const STATUSES = ["pending", "approved", "rejected", "sent"] as const;
type Status = (typeof STATUSES)[number];

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
  const { data, isLoading } = useAdminWithdrawals({ status });
  const decide = useAdminDecideWithdrawal();
  const toast = useToast();

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  const counters = data?.counters ?? {};

  return (
    <Page showBack onBack={() => navigate("/admin")}>
      <Header title="Выводы" subtitle="Заявки на вывод" />
      <div className="px-4 mb-3 flex gap-1.5 overflow-x-auto">
        {STATUSES.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatus(s)}
            className={`relative rounded-button px-3 py-1.5 text-sm transition shrink-0 ${
              s === status
                ? "bg-accent text-accent-fg font-medium"
                : "bg-panel text-text-muted"
            }`}
          >
            {labelOf(s)}
            {counters[s] !== undefined && counters[s] > 0 && (
              <span
                className={`ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full ${
                  s === status ? "bg-accent-fg/20" : "bg-panel-2 text-text"
                }`}
              >
                {counters[s]}
              </span>
            )}
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
                    {parseDecimal(w.amount).toFixed(8)} {w.currency_code}
                  </div>
                  <div className="text-xs text-text-muted">
                    @{w.username ?? "—"} ({w.display_name}) · #{w.id}
                  </div>
                  <div className="text-[11px] text-text-muted">
                    {new Date(w.created_at).toLocaleString()}
                  </div>
                </div>
              </div>
              <div className="bg-panel-2 rounded-button px-2 py-1.5 flex items-center gap-1.5">
                <span className="text-[11px] text-text-muted">Адрес:</span>
                <code className="text-xs flex-1 truncate font-mono">
                  {w.address}
                </code>
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(w.address);
                    toast.show({ kind: "info", title: "Скопировано" });
                  }}
                  className="text-text-muted active:scale-90"
                >
                  <Copy size={14} />
                </button>
              </div>
              {w.admin_note && (
                <div className="text-xs text-text-muted italic">
                  Комментарий: {w.admin_note}
                </div>
              )}
              {status === "pending" && (
                <div className="flex gap-2 pt-1">
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
                  <Button
                    type="button"
                    size="sm"
                    variant="danger"
                    onClick={async () => {
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
              {status === "approved" && (
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
    </Page>
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
