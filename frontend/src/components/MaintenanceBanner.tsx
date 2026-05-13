import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle } from "lucide-react";
import { api } from "@/api/client";
import type { MaintenanceStatusDto } from "@/api/types";

/**
 * Floating banner shown when `app_settings.maintenance_enabled=true`.
 *
 * Polls every 30s so flipping the switch in `/admin/settings` becomes
 * visible to all open clients within half a minute. Layout follows the
 * Continental design tokens (panel + accent border + 8px radius).
 */
export function MaintenanceBanner() {
  const { data } = useQuery<MaintenanceStatusDto>({
    queryKey: ["maintenance"],
    queryFn: () => api.get("api/settings/maintenance").json(),
    refetchInterval: 30_000,
    retry: false,
  });

  return (
    <AnimatePresence>
      {data?.enabled && (
        <motion.div
          initial={{ y: -40, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: -40, opacity: 0 }}
          transition={{ type: "spring", stiffness: 360, damping: 30 }}
          className="fixed inset-x-0 top-0 z-[70] px-3 pt-2 pointer-events-none"
        >
          <div className="mx-auto max-w-[460px] pointer-events-auto flex items-start gap-2 bg-warning/10 backdrop-blur border border-warning/40 rounded-card px-3 py-2 shadow-pop">
            <AlertTriangle size={16} className="text-warning shrink-0 mt-0.5" />
            <div className="text-sm">
              <div className="font-semibold text-warning">Технические работы</div>
              <div className="text-text-muted">{data.message}</div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
