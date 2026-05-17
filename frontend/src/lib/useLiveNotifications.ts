import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { connectNotifications, type WsEvent } from "@/lib/ws";
import { haptic } from "@/lib/tg";
import { useToast } from "@/components/ui/Toast";
import { qk } from "@/api/queryKeys";
import type { NotificationDto } from "@/api/types";
import type { DealMessageDto } from "@/api/hooks";

export function useLiveNotifications() {
  const qc = useQueryClient();
  const toast = useToast();
  // Keep ``toast`` reachable from the WS callback without tying the
  // effect's dependency array to its identity. ``ToastProvider``
  // memoises the current shape today, but any future state added to
  // the provider would re-create the object and the previous deps
  // ``[qc, toast]`` would tear the socket down + re-open it on every
  // render. Refs are read at call time so the latest provider shape
  // is always used.
  const toastRef = useRef(toast);
  toastRef.current = toast;

  useEffect(() => {
    const disconnect = connectNotifications({
      onEvent: (event: WsEvent) => {
        if (event.event === "deal_message" && event.data) {
          const msg = event.data as DealMessageDto;
          qc.setQueryData<DealMessageDto[] | undefined>(
            qk.deal.messages(msg.deal_id),
            (prev) => {
              if (!prev) return [msg];
              if (prev.some((m) => m.id === msg.id)) return prev;
              return [...prev, msg];
            },
          );
          haptic("light");
          return;
        }
        if (event.event !== "notification" || !event.data) return;
        const notif = event.data as NotificationDto;

        qc.setQueriesData<NotificationDto[] | undefined>(
          { queryKey: qk.notifications.all() },
          (prev) => {
            if (!prev) return prev;
            if (prev.some((n) => n.id === notif.id)) return prev;
            return [notif, ...prev];
          },
        );
        qc.invalidateQueries({ queryKey: qk.notifications.counters() });
        if (notif.type === "deals") {
          qc.invalidateQueries({ queryKey: qk.deals.all() });
          qc.invalidateQueries({ queryKey: qk.deal.all() });
        }
        if (notif.type === "deposits") {
          qc.invalidateQueries({ queryKey: qk.me() });
          // H-1 — legacy ``qk.payments`` was retired; wallet deposits
          // are surfaced through ``qk.wallet.*``.
          qc.invalidateQueries({ queryKey: qk.wallet.all() });
        }
        if (notif.type === "system") {
          qc.invalidateQueries({ queryKey: qk.reviews.all() });
          qc.invalidateQueries({ queryKey: qk.user.all() });
        }

        haptic("light");
        toastRef.current.show({
          kind: notif.type === "deals" ? "info" : notif.type === "deposits" ? "success" : "info",
          title: notif.title,
          body: notif.body,
        });
      },
    });
    return disconnect;
  }, [qc]);
}
