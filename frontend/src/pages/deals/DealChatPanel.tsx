import { useEffect, useRef, useState } from "react";
import { Paperclip, Send, X } from "lucide-react";
import {
  DEAL_MESSAGE_PAGE_SIZE,
  useDealMessages,
  useLoadOlderDealMessages,
  useMe,
  useSendDealMessage,
  useUploadMedia,
  type DealMessageDto,
  type MediaDto,
} from "@/api/hooks";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { haptic } from "@/lib/tg";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";

const MAX_ATTACHMENTS = 10;

interface DealChatPanelProps {
  dealId: number;
}

export function DealChatPanel({ dealId }: DealChatPanelProps) {
  const { data: me } = useMe();
  const { data: messages, isLoading } = useDealMessages(dealId);
  const sendMessage = useSendDealMessage(dealId);
  const loadOlder = useLoadOlderDealMessages(dealId);
  const uploadMedia = useUploadMedia();
  const toast = useToast();

  const [text, setText] = useState("");
  const [pending, setPending] = useState<MediaDto[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Audit H2 — the backend now returns at most
  // ``DEAL_MESSAGE_PAGE_SIZE`` messages. Once the user loads an older
  // page that comes back short, there is nothing left to fetch and the
  // "Load older" button hides itself.
  const [reachedOldest, setReachedOldest] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // After a "load older" we anchor the scroll position to the previous
  // top message so the user doesn't get teleported. ``stickToBottom``
  // is the default for new messages / initial render.
  const stickToBottomRef = useRef(true);
  const prevScrollHeightRef = useRef<number | null>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    } else if (prevScrollHeightRef.current != null) {
      // Preserve the user's visual position when older messages were
      // prepended.
      el.scrollTop = el.scrollHeight - prevScrollHeightRef.current;
      prevScrollHeightRef.current = null;
      stickToBottomRef.current = true;
    }
  }, [messages]);

  // Reset paging state if the user switches to a different deal.
  useEffect(() => {
    setReachedOldest(false);
  }, [dealId]);

  const onLoadOlder = async () => {
    if (!messages || messages.length === 0 || loadOlder.isPending) return;
    const oldest = messages[0];
    const el = scrollRef.current;
    prevScrollHeightRef.current = el ? el.scrollHeight : null;
    stickToBottomRef.current = false;
    try {
      const page = await loadOlder.mutateAsync({ beforeId: oldest.id });
      if (page.length < DEAL_MESSAGE_PAGE_SIZE) {
        setReachedOldest(true);
      }
    } catch (err) {
      stickToBottomRef.current = true;
      prevScrollHeightRef.current = null;
      const message = (err as Error)?.message || "Не удалось загрузить историю";
      toast.show({ kind: "error", title: message });
    }
  };

  const canLoadOlder =
    !reachedOldest && (messages?.length ?? 0) >= DEAL_MESSAGE_PAGE_SIZE;

  const onPickFiles = () => fileInputRef.current?.click();

  const onFilesSelected = async (
    e: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;
    if (pending.length + files.length > MAX_ATTACHMENTS) {
      setError(`Не больше ${MAX_ATTACHMENTS} вложений за сообщение`);
      haptic("error");
      return;
    }
    setError(null);
    setUploading(true);
    try {
      for (const file of files) {
        const media = await uploadMedia.mutateAsync({ kind: "deal", file });
        setPending((p) => [...p, media]);
      }
    } catch (err) {
      const message = (err as Error)?.message || "Не удалось загрузить файл";
      setError(message);
      toast.show({ kind: "error", title: message });
      haptic("error");
    } finally {
      setUploading(false);
    }
  };

  const removePending = (id: number) => {
    setPending((p) => p.filter((m) => m.id !== id));
  };

  const onSend = async () => {
    const trimmed = text.trim();
    if (!trimmed && pending.length === 0) return;
    setError(null);
    try {
      await sendMessage.mutateAsync({
        text: trimmed,
        attachments: pending.map((m) => m.id),
      });
      setText("");
      setPending([]);
      haptic("success");
    } catch (err) {
      const message = (err as Error)?.message || "Не удалось отправить";
      setError(message);
      toast.show({ kind: "error", title: message });
      haptic("error");
    }
  };

  return (
    <div className="bg-panel border border-border rounded-card p-4 space-y-3">
      <div className="text-sm text-text-muted">Чат сделки</div>

      <div
        ref={scrollRef}
        className="max-h-80 overflow-y-auto space-y-2 pr-1"
      >
        {isLoading && <Skeleton className="h-16" />}
        {!isLoading && canLoadOlder && (
          <div className="flex justify-center pb-2">
            <button
              type="button"
              onClick={onLoadOlder}
              disabled={loadOlder.isPending}
              className="text-xs text-text-muted hover:text-text disabled:opacity-50 underline-offset-2 hover:underline"
            >
              {loadOlder.isPending
                ? "Загружаю…"
                : "Показать более ранние"}
            </button>
          </div>
        )}
        {!isLoading && (!messages || messages.length === 0) && (
          <div className="text-xs text-text-muted text-center py-6">
            Сообщений пока нет
          </div>
        )}
        {messages?.map((msg) => (
          <MessageBubble
            key={msg.id}
            msg={msg}
            isMine={!!me && msg.sender_id === me.id}
          />
        ))}
      </div>

      {pending.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {pending.map((m) => (
            <AttachmentChip key={m.id} media={m} onRemove={() => removePending(m.id)} />
          ))}
        </div>
      )}

      {error && <div className="text-xs text-danger">{error}</div>}

      <div className="flex items-end gap-2">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="image/*"
          onChange={onFilesSelected}
          className="hidden"
        />
        <button
          type="button"
          onClick={onPickFiles}
          disabled={uploading || pending.length >= MAX_ATTACHMENTS}
          className="shrink-0 size-10 grid place-items-center rounded-card border border-border bg-panel-2 text-text-muted disabled:opacity-50"
          aria-label="Прикрепить файл"
        >
          <Paperclip className="size-5" />
        </button>
        <textarea
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Сообщение"
          className="flex-1 min-h-10 max-h-40 resize-none rounded-card border border-border bg-panel-2 px-3 py-2 text-sm"
        />
        <button
          type="button"
          onClick={onSend}
          disabled={
            sendMessage.isPending ||
            uploading ||
            (!text.trim() && pending.length === 0)
          }
          className={cn(
            "shrink-0 size-10 grid place-items-center rounded-card",
            "bg-accent text-bg disabled:opacity-50",
          )}
          aria-label="Отправить"
        >
          <Send className="size-5" />
        </button>
      </div>
    </div>
  );
}

function MessageBubble({
  msg,
  isMine,
}: {
  msg: DealMessageDto;
  isMine: boolean;
}) {
  return (
    <div className={cn("flex flex-col gap-1", isMine ? "items-end" : "items-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-card px-3 py-2 text-sm",
          isMine
            ? "bg-accent text-bg"
            : "bg-panel-2 border border-border text-text",
        )}
      >
        {!isMine && msg.sender_username && (
          <div className="text-[10px] text-text-muted mb-0.5">
            @{msg.sender_username}
          </div>
        )}
        {msg.text && <div className="whitespace-pre-wrap break-words">{msg.text}</div>}
        {msg.attachments.length > 0 && (
          <div className="mt-2 grid grid-cols-2 gap-1">
            {msg.attachments.map((m) => (
              <a
                key={m.id}
                href={m.url}
                target="_blank"
                rel="noreferrer"
                className="block overflow-hidden rounded-md bg-panel"
              >
                <img
                  src={m.url}
                  alt={m.name}
                  className="w-full h-24 object-cover"
                  loading="lazy"
                />
              </a>
            ))}
          </div>
        )}
      </div>
      <div className="text-[10px] text-text-muted px-1">
        {relativeTime(msg.created_at)}
      </div>
    </div>
  );
}

function AttachmentChip({
  media,
  onRemove,
}: {
  media: MediaDto;
  onRemove: () => void;
}) {
  return (
    <div className="relative">
      <img
        src={media.url}
        alt={media.name}
        className="size-16 object-cover rounded-md border border-border"
      />
      <button
        type="button"
        onClick={onRemove}
        className="absolute -top-1 -right-1 size-5 grid place-items-center rounded-full bg-danger text-white"
        aria-label="Убрать вложение"
      >
        <X className="size-3" />
      </button>
    </div>
  );
}
