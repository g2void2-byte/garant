import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { api } from "@/api/client";
import { qk } from "@/api/queryKeys";
import type { MaintenanceStatusDto } from "@/api/types";

export function MaintenanceBanner() {
  const { data } = useQuery<MaintenanceStatusDto>({
    queryKey: qk.maintenance(),
    queryFn: () => api.get("api/settings/maintenance").json(),
    refetchInterval: 30_000,
    retry: false,
  });

  if (!data?.enabled) return null;

  return (
    <div className="fixed inset-x-0 top-0 z-[70] px-3 pt-2 pointer-events-none animate-slide-down-banner">
      <div className="mx-auto max-w-[460px] pointer-events-auto flex items-start gap-2 bg-warning/10 backdrop-blur border border-warning/40 rounded-card px-3 py-2 shadow-pop">
        <AlertTriangle size={16} className="text-warning shrink-0 mt-0.5" />
        <div className="text-sm">
          <div className="font-semibold text-warning">Технические работы</div>
          <div className="text-text-muted">{data.message}</div>
        </div>
      </div>
    </div>
  );
}
