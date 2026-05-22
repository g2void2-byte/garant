import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { connectNotifications, type WsEvent } from "@/lib/ws";
import { haptic } from "@/lib/tg";
import { clearPinToken } from "@/lib/pin";
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
        if (event.event === "deal.updated") {
          // Item 22 — transient cache-invalidation signal. Sent by the
          // backend after every state-changing deal op so every party
          // (initiator + counterparty + arbiter) re-pulls the deal
          // without waiting for the next focus / poll refetch.
          const data = event.data as { deal_id?: number } | undefined;
          if (data?.deal_id) {
            qc.invalidateQueries({ queryKey: qk.deal.detail(data.deal_id) });
          }
          qc.invalidateQueries({ queryKey: qk.deals.all() });
          qc.invalidateQueries({ queryKey: qk.deal.all() });
          return;
        }
        if (event.event === "pin.reset") {
          // Item 8 — admin pressed "reset PIN" on this user. Drop the
          // locally cached PIN token (the ``garant:pin-token-changed``
          // event flips ``PinGate`` out of the authenticated tree) and
          // refetch ``pin/status`` so the gate sees ``has_pin=false``
          // and routes the user into the "set new PIN" flow rather
          // than the "enter PIN" one.
          clearPinToken();
          qc.invalidateQueries({ queryKey: qk.pin.all() });
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
