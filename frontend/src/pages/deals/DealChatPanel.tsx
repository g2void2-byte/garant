import { useEffect, useMemo, useRef, useState } from "react";
import { Send } from "lucide-react";
import {
  useDealMessages,
  useMarkDealMessagesRead,
  useMe,
  useSendDealMessage,
} from "@/api/hooks";
import type { DealMessageDto } from "@/api/types";
import { Avatar } from "@/components/ui/Avatar";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { haptic } from "@/lib/tg";

interface DealChatPanelProps {
  dealId: number;
  /**
   * If true, the message input is hidden (e.g. for arbiters/admins that
   * only read, or for terminal-status deals).
   */
  readOnly?: boolean;
  /**
   * Short message rendered above the input when ``readOnly`` is true.
   */
  readOnlyHint?: string;
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function groupByDay(msgs: DealMessageDto[]): {
  key: string;
  label: string;
  items: DealMessageDto[];
}[] {
  const out: { key: string; label: string; items: DealMessageDto[] }[] = [];
  for (const msg of msgs) {
    const iso = msg.created_at ?? "";
    const day = iso.slice(0, 10);
    const last = out[out.length - 1];
    if (last && last.key === day) {
      last.items.push(msg);
    } else {
      const date = day ? new Date(day) : new Date();
      const label = Number.isNaN(date.getTime())
        ? ""
        : date.toLocaleDateString("ru-RU", {
            day: "numeric",
            month: "long",
          });
      out.push({ key: day, label, items: [msg] });
    }
  }
  return out;
}

export function DealChatPanel({
  dealId,
  readOnly,
  readOnlyHint,
}: DealChatPanelProps) {
  const toast = useToast();
  const { data, isLoading } = useDealMessages(dealId);
  const { data: me } = useMe();
  const send = useSendDealMessage(dealId);
  const markRead = useMarkDealMessagesRead();

  const [body, setBody] = useState("");
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const seenIdRef = useRef<number | null>(null);

  const messages = useMemo(() => data?.items ?? [], [data?.items]);
  const lastId = messages.length ? messages[messages.length - 1].id : null;

  useEffect(() => {
    if (lastId === null) return;
    if (seenIdRef.current === lastId) return;
    seenIdRef.current = lastId;
    const el = scrollerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastId]);

  useEffect(() => {
    if (!dealId) return;
    if (!data || data.unread <= 0) return;
    markRead.mutate(dealId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId, data?.unread]);

  const submit = async () => {
    const text = body.trim();
    if (!text) return;
    try {
      await send.mutateAsync(text);
      setBody("");
      haptic("light");
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Не удалось отправить сообщение",
      });
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const groups = useMemo(() => groupByDay(messages), [messages]);

  return (
    <div className="flex flex-col bg-panel border border-border rounded-card overflow-hidden">
      <div
        ref={scrollerRef}
        className="px-3 py-3 space-y-2 max-h-[60vh] overflow-y-auto"
      >
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : messages.length === 0 ? (
          <div className="text-sm text-text-muted text-center py-6">
            Сообщений пока нет. Напишите первым.
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.key} className="space-y-2">
              {group.label && (
                <div className="text-center text-[11px] uppercase tracking-wider text-text-muted py-1">
                  {group.label}
                </div>
              )}
              {group.items.map((msg) => {
                if (msg.kind === "system") {
                  return (
                    <div
                      key={msg.id}
                      className="text-[12px] text-text-muted text-center py-1 px-3 whitespace-pre-wrap"
                    >
                      {msg.body}
                    </div>
                  );
                }
                const own = !!me && msg.author?.id === me.id;
                return (
                  <div
                    key={msg.id}
                    className={cn(
                      "flex gap-2 items-end",
                      own ? "flex-row-reverse" : "flex-row",
                    )}
                  >
                    {!own && (
                      <Avatar
                        size={28}
                        name={
                          msg.author?.username ||
                          msg.author?.display_name ||
                          "?"
                        }
                        src={msg.author?.photo_url ?? undefined}
                      />
                    )}
                    <div
                      className={cn(
                        "max-w-[78%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap break-words",
                        own
                          ? "bg-accent/15 border border-accent/40 text-text"
                          : "bg-panel-2 border border-border text-text",
                      )}
                    >
                      {!own && msg.author && (
                        <div className="text-[11px] text-text-muted mb-0.5">
                          @{msg.author.username || msg.author.display_name}
                        </div>
                      )}
                      <div>{msg.body}</div>
                      <div className="text-[10px] text-text-muted mt-0.5 text-right">
                        {formatTime(msg.created_at)}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ))
        )}
      </div>

      {readOnly ? (
        <div className="border-t border-border p-3 text-xs text-text-muted">
          {readOnlyHint ?? "Чат закрыт."}
        </div>
      ) : (
        <div className="border-t border-border p-2 flex items-end gap-2">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={onKey}
            rows={1}
            maxLength={4000}
            placeholder="Сообщение..."
            className="flex-1 max-h-32 resize-none p-2 rounded-2xl bg-panel-2 border border-border text-text placeholder:text-text-muted focus:outline-none focus:border-accent transition-colors"
          />
          <button
            type="button"
            onClick={submit}
            disabled={!body.trim() || send.isPending}
            className={cn(
              "size-10 grid place-items-center rounded-full transition-colors",
              !body.trim() || send.isPending
                ? "bg-panel-2 text-text-muted"
                : "bg-accent text-accent-fg",
            )}
            aria-label="Отправить"
          >
            <Send className="size-4" />
          </button>
        </div>
      )}
    </div>
  );
}
