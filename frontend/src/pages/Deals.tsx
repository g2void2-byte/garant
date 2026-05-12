import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";

import { api, type Deal, type DealStatus } from "@/api";
import { Money, StatusPill } from "@/components/ui";
import { useUser } from "@/store";
import { useState } from "react";

const STATUS_TABS: { id: DealStatus | "all"; label: string }[] = [
  { id: "all", label: "Все" },
  { id: "awaiting_payment", label: "Ждут оплаты" },
  { id: "funded", label: "Эскроу" },
  { id: "completed", label: "Готово" },
  { id: "disputed", label: "Споры" },
];

export default function Deals() {
  const [tab, setTab] = useState<DealStatus | "all">("all");
  const { user } = useUser();
  const { data: deals = [], isLoading } = useQuery({
    queryKey: ["deals", tab],
    queryFn: () => api.listDeals(tab === "all" ? undefined : tab),
  });

  return (
    <div className="flex flex-col gap-4 px-4 pt-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Сделки</h1>
        <Link to="/deals/new" className="btn-primary">
          ➕ Новая
        </Link>
      </div>

      <div className="-mx-2 flex gap-2 overflow-x-auto px-2 pb-1">
        {STATUS_TABS.map((s) => (
          <button
            key={s.id}
            onClick={() => setTab(s.id)}
            className={`pill whitespace-nowrap ${
              tab === s.id
                ? "bg-brand text-bg"
                : "bg-bg-card/60 text-white/70 hover:text-white"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {isLoading && <Skeleton />}
      {!isLoading && deals.length === 0 && <EmptyState />}

      <div className="flex flex-col gap-3">
        {deals.map((d) => (
          <DealCard key={d.id} deal={d} isBuyer={d.buyer.id === user?.id} />
        ))}
      </div>
    </div>
  );
}

function DealCard({ deal, isBuyer }: { deal: Deal; isBuyer: boolean }) {
  const cp = isBuyer ? deal.seller : deal.buyer;
  return (
    <motion.div
      whileTap={{ scale: 0.98 }}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
    >
      <Link
        to={`/deals/${deal.id}`}
        className="glass-card block p-4 transition hover:border-brand/30"
      >
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="truncate text-base font-semibold">{deal.title}</div>
          <StatusPill status={deal.status} />
        </div>
        <div className="flex items-center justify-between text-sm text-white/60">
          <div>
            {isBuyer ? "Продавец" : "Покупатель"}:{" "}
            <span className="text-white/80">
              {cp.username ? `@${cp.username}` : (cp.first_name ?? "—")}
            </span>
          </div>
          <Money value={deal.amount} className="text-base font-semibold text-brand" />
        </div>
      </Link>
    </motion.div>
  );
}

function EmptyState() {
  return (
    <div className="glass-card p-8 text-center">
      <div className="mb-2 text-4xl">📭</div>
      <div className="text-lg font-semibold">Пока нет сделок</div>
      <p className="mt-1 text-sm text-white/55">
        Создайте первую — это займёт меньше минуты.
      </p>
      <Link to="/deals/new" className="btn-primary mt-4 inline-flex">
        ➕ Создать сделку
      </Link>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="glass-card h-20 animate-pulse bg-bg-card/40"
        />
      ))}
    </div>
  );
}
