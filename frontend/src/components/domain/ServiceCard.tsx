import { motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import type { ServiceDto } from "@/api/types";
import { formatMoney } from "@/lib/format";

export function ServiceCard({ service, index = 0 }: { service: ServiceDto; index?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.03, 0.3), duration: 0.2 }}
      className="bg-panel border border-border rounded-card p-3"
    >
      <Link to={`/u/${service.owner_username}`} className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-[11px] uppercase tracking-wide text-text-muted">{service.category.name}</div>
          <div className="mt-0.5 font-semibold truncate">{service.title}</div>
          {service.description && (
            <div className="mt-1 text-sm text-text-muted line-clamp-2">{service.description}</div>
          )}
          <div className="mt-2 flex items-center gap-2 text-xs text-text-muted">
            <span>@{service.owner_username}</span>
            <span>·</span>
            <span className="text-accent font-semibold">{formatMoney(service.price)}</span>
          </div>
        </div>
        <ChevronRight className="size-5 text-text-muted shrink-0" />
      </Link>
    </motion.div>
  );
}
