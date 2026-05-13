import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { connectNotifications, type WsEvent } from "@/lib/ws";
import { haptic } from "@/lib/tg";
import { useToast } from "@/components/ui/Toast";
import type { NotificationDto } from "@/api/types";

export function useLiveNotifications() {
  const qc = useQueryClient();
  const toast = useToast();

  useEffect(() => {
    const disconnect = connectNotifications({
      onEvent: (event: WsEvent) => {
        if (event.event !== "notification" || !event.data) return;
        const notif = event.data as NotificationDto;

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
