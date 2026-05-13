import { motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import type { DealDto } from "@/api/types";
import { formatMoney, relativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";

const STATUS_LABEL: Record<string, { text: string; cls: string; icon: string }> = {
  wait_confirm: { text: "Ожидает подтверждения", cls: "bg-[#48390F] text-accent", icon: "⏳" },
  confirmed: { text: "Подтверждена", cls: "bg-success/15 text-success", icon: "✅" },
  success: { text: "Успех", cls: "bg-success/15 text-success", icon: "🎉" },
  failed: { text: "Отменена", cls: "bg-danger/15 text-danger", icon: "❌" },
  arbitrage: { text: "Арбитраж", cls: "bg-accent/15 text-accent", icon: "⚖️" },
  wait_final_confirm: { text: "Финальное подтверждение", cls: "bg-accent/15 text-accent", icon: "⏳" },
};

export function DealRow({ deal, index = 0 }: { deal: DealDto; index?: number }) {
  const status = STATUS_LABEL[deal.status] ?? { text: deal.status, cls: "bg-panel-2 text-text-muted", icon: "•" };
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.025, 0.25), duration: 0.2 }}
    >
      <Link to={`/deals/${deal.id}`} className="block bg-panel border border-border rounded-card p-3 active:scale-[.99] transition-transform">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold", status.cls)}>
                <span>{status.icon}</span>
                <span>{status.text}</span>
              </span>
              <span className="text-[11px] uppercase tracking-wide text-text-muted">#{deal.id}</span>
            </div>
            <div className="mt-2 font-semibold line-clamp-1">{deal.description}</div>
            <div className="mt-1 flex items-center gap-2 text-xs text-text-muted">
              <span>{deal.role === "buyer" ? `Продавец: @${deal.seller}` : `Покупатель: @${deal.buyer}`}</span>
              {deal.created_at && (
                <>
                  <span>·</span>
                  <span>{relativeTime(deal.created_at)}</span>
                </>
              )}
            </div>
          </div>
          <div className="text-right shrink-0">
            <div className="text-accent font-bold">{formatMoney(deal.sum)}</div>
            <div className="mt-1 inline-flex items-center text-text-muted text-xs">
              {deal.role === "buyer" ? "Покупка" : "Продажа"} <ChevronRight className="size-3" />
            </div>
          </div>
        </div>
      </Link>
    </motion.div>
  );
}
