import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { connectNotifications, type WsEvent } from "@/lib/ws";
import { haptic } from "@/lib/tg";
import { clearPinToken } from "@/lib/pin";
import { useToast } from "@/components/ui/Toast";
import { qk } from "@/api/queryKeys";
import type { DealMessageDto, MediaDto, NotificationDto } from "@/api/types";
import { isPositiveSafeInteger, parsePositiveIntValue } from "@/lib/routeParams";
import { safeMediaUrl } from "@/lib/mediaLinks";
import {
  applyServerNotificationRead,
  invalidateDealParticipantSideEffects,
} from "@/api/hooks";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveSafeIntValue(value: unknown): value is number {
  return typeof value === "number" && isPositiveSafeInteger(value);
}

function hasSameRuntimePositiveId(left: unknown, right: unknown): boolean {
  const parsedLeft = parsePositiveIntValue(left);
  const parsedRight = parsePositiveIntValue(right);
  if (parsedLeft !== undefined && parsedRight !== undefined) {
    return parsedLeft === parsedRight;
  }
  return left === right;
}

function isNonNegativeSafeIntValue(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isMediaDto(value: unknown): value is MediaDto {
  if (!isRecord(value)) return false;
  return (
    isPositiveSafeIntValue(value.id) &&
    typeof value.kind === "string" &&
    typeof value.url === "string" &&
    safeMediaUrl(value.url) !== null &&
    typeof value.name === "string" &&
    isNonNegativeSafeIntValue(value.size) &&
    typeof value.content_type === "string" &&
    (typeof value.created_at === "string" || value.created_at === null)
  );
}

function isDealMessageDto(value: unknown): value is DealMessageDto {
  if (!isRecord(value)) return false;
  return (
    isPositiveSafeIntValue(value.id) &&
    isPositiveSafeIntValue(value.deal_id) &&
    isPositiveSafeIntValue(value.sender_id) &&
    (typeof value.sender_username === "string" || value.sender_username === null) &&
    typeof value.text === "string" &&
    Array.isArray(value.attachments) &&
    value.attachments.every(isMediaDto) &&
    typeof value.created_at === "string"
  );
}

function isNotificationDto(value: unknown): value is NotificationDto {
  if (!isRecord(value)) return false;
  return (
    isPositiveSafeIntValue(value.id) &&
    (value.type === "deals" || value.type === "deposits" || value.type === "system") &&
    typeof value.title === "string" &&
    typeof value.body === "string" &&
    (isRecord(value.payload) || value.payload === null) &&
    typeof value.is_read === "boolean" &&
    typeof value.created_at === "string"
  );
}

function parseNotificationReadPayload(value: unknown): { ids?: number[]; all?: boolean } | null {
  if (!isRecord(value)) return null;
  const payload: { ids?: number[]; all?: boolean } = {};
  if (value.all !== undefined) {
    if (typeof value.all !== "boolean") return null;
    if (value.all) payload.all = true;
  }
  if (value.ids !== undefined) {
    if (!Array.isArray(value.ids)) return null;
    if (!value.ids.every(isPositiveSafeIntValue)) return null;
    if (value.ids.length > 0) payload.ids = value.ids;
  }
  return payload.all || payload.ids ? payload : null;
}

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
          if (!isDealMessageDto(event.data)) return;
          const msg = event.data;
          qc.setQueryData<DealMessageDto[] | undefined>(
            qk.deal.messages(msg.deal_id),
            (prev) => {
              if (!prev) return [msg];
              if (prev.some((m) => hasSameRuntimePositiveId(m.id, msg.id))) return prev;
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
          const data = isRecord(event.data) ? event.data : undefined;
          if (isPositiveSafeIntValue(data?.deal_id)) {
            qc.invalidateQueries({ queryKey: qk.deal.detail(data.deal_id) });
          }
          qc.invalidateQueries({ queryKey: qk.deals.all() });
          qc.invalidateQueries({ queryKey: qk.deal.all() });
          invalidateDealParticipantSideEffects(qc);
          return;
        }
        if (event.event === "notification.read") {
          // Bug-13 — another tab / device marked notifications read.
          // Splice ``is_read=true`` into our local list cache and
          // decrement counters in place so the bell badge updates
          // without waiting for the next 30-second poll.
          const data = parseNotificationReadPayload(event.data);
          if (data) {
            applyServerNotificationRead(qc, data);
          }
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
        if (!isNotificationDto(event.data)) return;
        const notif = event.data;

        qc.setQueriesData<NotificationDto[] | undefined>(
          { queryKey: qk.notifications.all() },
          (prev) => {
            if (!prev) return prev;
            if (prev.some((n) => hasSameRuntimePositiveId(n.id, notif.id))) return prev;
            return [notif, ...prev];
          },
        );
        qc.invalidateQueries({ queryKey: qk.notifications.counters() });
        if (notif.type === "deals") {
          qc.invalidateQueries({ queryKey: qk.deals.all() });
          qc.invalidateQueries({ queryKey: qk.deal.all() });
          invalidateDealParticipantSideEffects(qc);
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
