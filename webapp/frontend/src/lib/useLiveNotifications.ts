import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { connectNotifications, type WsEvent } from "@/lib/ws";
import { haptic } from "@/lib/tg";
import { useToast } from "@/components/ui/Toast";
import type { NotificationDto } from "@/api/types";

/**
 * Connects to the FastAPI notifications WebSocket and fans out events
 * to TanStack Query (so badges + lists update without a refetch) and to
 * the toast viewport (so the user sees a banner). Idempotent — calling
 * it from a single high-level component is sufficient.
 */
export function useLiveNotifications() {
  const qc = useQueryClient();
  const toast = useToast();

  useEffect(() => {
    const disconnect = connectNotifications({
      onEvent: (event: WsEvent) => {
        if (event.event !== "notification" || !event.data) return;
        const notif = event.data as NotificationDto;

        // Optimistically insert the notification into any cached list that
        // is relevant for its type, and refresh the counters/queries that
        // back the badges + detail pages.
        qc.setQueriesData<NotificationDto[] | undefined>(
          { queryKey: ["notifications"] },
          (prev) => {
            if (!prev) return prev;
            if (prev.some((n) => n.id === notif.id)) return prev;
            return [notif, ...prev];
          },
        );
        qc.invalidateQueries({ queryKey: ["notifications", "counters"] });
        if (notif.type === "deals") {
          qc.invalidateQueries({ queryKey: ["deals"] });
          qc.invalidateQueries({ queryKey: ["deal"] });
        }
        if (notif.type === "deposits") {
          qc.invalidateQueries({ queryKey: ["me"] });
          qc.invalidateQueries({ queryKey: ["payments"] });
        }
        if (notif.type === "system") {
          qc.invalidateQueries({ queryKey: ["reviews"] });
          qc.invalidateQueries({ queryKey: ["user"] });
        }

        haptic("light");
        toast.show({
          kind: notif.type === "deals" ? "info" : notif.type === "deposits" ? "success" : "info",
          title: notif.title,
          body: notif.body,
        });
      },
    });
    return disconnect;
  }, [qc, toast]);
}
