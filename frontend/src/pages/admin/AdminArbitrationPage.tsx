import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCheck, ChevronLeft, ChevronRight, Gavel, Inbox, type LucideIcon } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { useAdminArbitration, useAdminClaimArbitration } from "@/api/admin/hooks";
import type { AdminDealListItemDto } from "@/api/types";
import { haptic } from "@/lib/tg";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";
import { formatAdminAmount, formatAdminUsername } from "./format";

type Queue = "new" | "in_progress" | "closed";
const PAGE_SIZE = 20;

const QUEUE_TABS: Array<{ key: Queue; label: string; icon: LucideIcon }> = [
  { key: "new", label: "Новые", icon: Inbox },
  { key: "in_progress", label: "В работе", icon: Gavel },
  { key: "closed", label: "Закрытые", icon: CheckCheck },
];

/**
 * Continental admin arbitration queue.
 *
 * Three-tab switcher with badge counters:
 *   * new        — без арбитра, кнопка «Взять в работу» (atomic claim)
 *   * in_progress — assigned arbiter, tap to open detail
 *   * closed      — resolved
 *
 * Arbiters see all queues; admin can claim too (admin auto-becomes
 * arbiter for that deal).
 */
export default function AdminArbitrationPage() {
  const navigate = useNavigate();
  const [queue, setQueue] = useState<Queue>("new");
  const [page, setPage] = useState(1);
  const { data, isLoading } = useAdminArbitration(queue, page, PAGE_SIZE);
  const toast = useToast();
  const claim = useAdminClaimArbitration();

  const __guard = useAdminRedirect({ allowArbiter: true });
  if (!__guard.shouldRender) return null;

  const items = data?.items ?? [];
  const counters = data?.counters ?? { new: 0, in_progress: 0, closed: 0 };

  const onClaim = async (dealId: number) => {
    haptic("medium");
    try {
      await claim.mutateAsync(dealId);
      toast.show({ kind: "success", title: "Дело взято в работу" });
      setQueue("in_progress");
      setPage(1);
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      if (status === 409) {
        toast.show({ kind: "error", title: "Дело уже занято", body: "Кто-то опередил вас" });
      } else {
        toast.show({ kind: "error", title: "Не удалось взять", body: (e as Error)?.message ?? "" });
      }
    }
  };

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader title="Арбитраж" subtitle="Очередь споров" />

      <div className="px-4 grid grid-cols-3 gap-2 mb-3">
        {QUEUE_TABS.map((t) => {
          const count = counters[t.key];
          const active = queue === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => {
                haptic("light");
                setQueue(t.key);
                setPage(1);
              }}
              className={`relative flex flex-col items-center justify-center rounded-card py-2.5 transition-colors ${
                active ? "bg-accent text-black" : "bg-panel text-text-muted"
              }`}
            >
              <t.icon size={16} />
              <span className="mt-1 text-[11px] font-medium">{t.label}</span>
              {count > 0 && (
                <span
                  className={`absolute top-1 right-1 min-w-[18px] h-[18px] rounded-full px-1 text-[10px] font-bold grid place-items-center ${
                    active ? "bg-black text-accent" : "bg-accent text-black"
                  }`}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <div className="px-4 space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Gavel size={20} />}
          title={
            queue === "new"
              ? "Очередь пуста"
              : queue === "in_progress"
              ? "Нет активных дел"
              : "Закрытых дел нет"
          }
          description={
            queue === "new" ? "Новые споры появятся здесь." : undefined
          }
        />
      ) : (
        <ul className="px-4 space-y-2">
          {items.map((d, _idx) => (
            <li
              key={d.id}
            >
              <ArbRow
                deal={d}
                queue={queue}
                onOpen={() => navigate(`/admin/deals/${d.id}`)}
                onClaim={() => onClaim(d.id)}
                claiming={claim.isPending}
              />
            </li>
          ))}
        </ul>
      )}
      {Math.ceil((counters[queue] ?? 0) / PAGE_SIZE) > 1 && (
        <Pagination
          page={page}
          totalPages={Math.max(1, Math.ceil((counters[queue] ?? 0) / PAGE_SIZE))}
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
    <div className="flex items-center justify-center gap-3 mt-3 mb-4 text-sm">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        className="p-2 rounded-button bg-panel disabled:opacity-40 active:scale-95"
        aria-label={"\u041d\u0430\u0437\u0430\u0434"}
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
        aria-label={"\u0412\u043f\u0435\u0440\u0451\u0434"}
      >
        <ChevronRight size={18} />
      </button>
    </div>
  );
}

function ArbRow({
  deal,
  queue,
  onOpen,
  onClaim,
  claiming,
}: {
  deal: AdminDealListItemDto;
  queue: Queue;
  onOpen: () => void;
  onClaim: () => void;
  claiming: boolean;
}) {
  return (
    <div className="bg-panel rounded-card p-3 border border-danger/20">
      <button type="button" onClick={onOpen} className="w-full text-left">
        <div className="flex items-center gap-1.5 text-sm font-semibold">
          <span>#{deal.id}</span>
          <span className="text-text-muted">·</span>
          <span className="text-text-muted truncate">
            {formatAdminUsername(deal.buyer_username)} ↔ {formatAdminUsername(deal.seller_username)}
          </span>
          <ChevronRight size={14} className="text-text-muted ml-auto shrink-0" />
        </div>
        <div className="mt-0.5 text-xs text-text-muted flex items-center gap-2 flex-wrap">
          <span className="font-medium text-text">
            {formatAdminAmount(deal.amount)}{" "}
            {deal.currency_code ?? "USD"}
          </span>
          <span>·</span>
          <span>Арбитраж</span>
        </div>
      </button>
      {queue === "new" && (
        <Button
          size="sm"
          fullWidth
          variant="primary"
          className="mt-3"
          disabled={claiming}
          onClick={onClaim}
        >
          {claiming ? "..." : "Взять в работу"}
        </Button>
      )}
    </div>
  );
}
