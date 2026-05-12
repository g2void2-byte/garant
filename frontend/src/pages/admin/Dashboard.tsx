import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";

import { api } from "@/api";
import { Money } from "@/components/ui";

export default function Dashboard() {
  const { data } = useQuery({ queryKey: ["admin-stats"], queryFn: api.admin.stats });
  if (!data)
    return (
      <div className="glass-card h-40 animate-pulse" />
    );

  const cards: { label: string; value: React.ReactNode; accent?: boolean }[] = [
    { label: "Пользователей", value: data.users_total },
    { label: "Активны за 7 дней", value: data.users_active_7d },
    { label: "Сделок всего", value: data.deals_total },
    { label: "В эскроу сейчас", value: data.deals_in_escrow, accent: true },
    { label: "Оборот", value: <Money value={data.volume_total} /> },
    { label: "Доход (комиссия)", value: <Money value={data.commission_total} />, accent: true },
  ];
  return (
    <div className="grid grid-cols-2 gap-3">
      {cards.map((c, i) => (
        <motion.div
          key={c.label}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05 }}
          className="glass-card p-4"
        >
          <div className="text-xs uppercase tracking-wide text-white/45">
            {c.label}
          </div>
          <div
            className={`mt-1 text-2xl font-bold ${
              c.accent ? "text-brand" : ""
            }`}
          >
            {c.value}
          </div>
        </motion.div>
      ))}
    </div>
  );
}
