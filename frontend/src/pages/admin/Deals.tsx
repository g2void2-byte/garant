import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type Deal, type DealStatus } from "@/api";
import { Money, StatusPill } from "@/components/ui";
import { notify } from "@/telegram";

const STATUS_TABS: { id: DealStatus | "all"; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "funded", label: "В эскроу" },
  { id: "disputed", label: "Споры" },
  { id: "completed", label: "Завершены" },
  { id: "refunded", label: "Возвраты" },
];

export default function Deals() {
  const [tab, setTab] = useState<DealStatus | "all">("all");
  const qc = useQueryClient();
  const { data: deals = [] } = useQuery({
    queryKey: ["admin-deals", tab],
    queryFn: () => api.admin.listDeals(tab === "all" ? undefined : tab),
  });

  return (
    <div className="space-y-3">
      <div className="-mx-2 flex gap-2 overflow-x-auto px-2">
        {STATUS_TABS.map((s) => (
          <button
            key={s.id}
            onClick={() => setTab(s.id)}
            className={`pill whitespace-nowrap ${
              tab === s.id ? "bg-brand text-bg" : "bg-bg-card/60 text-white/70"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>
      {deals.map((d) => (
        <Row
          key={d.id}
          deal={d}
          onChange={() => qc.invalidateQueries({ queryKey: ["admin-deals"] })}
        />
      ))}
      {deals.length === 0 && (
        <div className="glass-card p-6 text-center text-white/50">Пусто</div>
      )}
    </div>
  );
}

function Row({ deal, onChange }: { deal: Deal; onChange: () => void }) {
  const force = useMutation({
    mutationFn: (action: "release" | "refund") =>
      action === "release"
        ? api.admin.forceRelease(deal.id)
        : api.admin.forceRefund(deal.id),
    onSuccess: () => {
      notify("success");
      onChange();
    },
    onError: (e) => alert((e as Error).message),
  });

  return (
    <div className="glass-card p-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="min-w-0 truncate text-base font-semibold">
          #{deal.id} · {deal.title}
        </div>
        <StatusPill status={deal.status} />
      </div>
      <div className="grid grid-cols-2 gap-2 text-sm text-white/70">
        <div>
          Покупатель:{" "}
          <span className="text-white">
            {deal.buyer.username ? `@${deal.buyer.username}` : deal.buyer.tg_id}
          </span>
        </div>
        <div>
          Продавец:{" "}
          <span className="text-white">
            {deal.seller.username ? `@${deal.seller.username}` : deal.seller.tg_id}
          </span>
        </div>
        <div>
          Сумма: <Money value={deal.amount} className="text-brand" />
        </div>
        <div>
          Комиссия: <Money value={deal.commission} />
        </div>
      </div>
      {deal.dispute_reason && (
        <div className="mt-2 rounded-xl bg-rose-500/10 p-2 text-xs text-rose-200">
          Спор: {deal.dispute_reason}
        </div>
      )}
      {(deal.status === "funded" || deal.status === "disputed") && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button
            onClick={() => force.mutate("release")}
            className="btn-primary"
            disabled={force.isPending}
          >
            ✅ Завершить (продавцу)
          </button>
          <button
            onClick={() => force.mutate("refund")}
            className="btn-danger"
            disabled={force.isPending}
          >
            ↩ Вернуть (покупателю)
          </button>
        </div>
      )}
    </div>
  );
}
