import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ChevronRight, Gavel, Inbox, CheckCheck, type LucideIcon } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { useAdminArbitration, useAdminClaimArbitration } from "@/api/admin/hooks";
import { useMe } from "@/api/hooks";
import type { AdminDealListItemDto } from "@/api/types";
import { haptic } from "@/lib/tg";

type Queue = "new" | "in_progress" | "closed";

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
  const { data: me } = useMe();
  const [queue, setQueue] = useState<Queue>("new");
  const { data, isLoading } = useAdminArbitration(queue);
  const toast = useToast();
  const claim = useAdminClaimArbitration();

  if (me && !me.is_admin && !me.is_arbiter) {
    navigate("/search", { replace: true });
    return null;
  }

  const items = data?.items ?? [];
  const counters = data?.counters ?? { new: 0, in_progress: 0, closed: 0 };

  const onClaim = async (dealId: number) => {
    haptic("medium");
    try {
      await claim.mutateAsync(dealId);
      toast.show({ kind: "success", title: "Дело взято в работу" });
      setQueue("in_progress");
    } catch (e: any) {
      const status = e?.response?.status;
      if (status === 409) {
        toast.show({ kind: "error", title: "Дело уже занято", body: "Кто-то опередил вас" });
      } else {
        toast.show({ kind: "error", title: "Не удалось взять", body: e?.message ?? "" });
      }
    }
  };

  return (
    <Page showBack onBack={() => navigate("/admin")}>
      <Header title="Арбитраж" subtitle="Очередь споров" />

      <div className="px-4 grid grid-cols-3 gap-2 mb-3">
        {QUEUE_TABS.map((t) => {
          const count = counters[t.key];
          const active = queue === t.key;
          return (
            <motion.button
              key={t.key}
              type="button"
              whileTap={{ scale: 0.97 }}
              onClick={() => {
                haptic("light");
                setQueue(t.key);
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
            </motion.button>
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
          {items.map((d, idx) => (
            <motion.li
              key={d.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: Math.min(idx, 8) * 0.03, duration: 0.18 }}
            >
              <ArbRow
                deal={d}
                queue={queue}
                onOpen={() => navigate(`/admin/deals/${d.id}`)}
                onClaim={() => onClaim(d.id)}
                claiming={claim.isPending}
              />
            </motion.li>
          ))}
        </ul>
      )}
    </Page>
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
            @{deal.buyer_username ?? "—"} ↔ @{deal.seller_username ?? "—"}
          </span>
          <ChevronRight size={14} className="text-text-muted ml-auto shrink-0" />
        </div>
        <div className="mt-0.5 text-xs text-text-muted flex items-center gap-2 flex-wrap">
          <span className="font-medium text-text">
            {deal.amount?.toFixed(2) ?? deal.sum.toFixed(2)} {deal.currency_code ?? "USD"}
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
