import { useEffect, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Bell, Briefcase, ExternalLink, Wallet } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  useMarkNotificationRead,
  useNotification,
} from "@/api/hooks";
import { relativeTime } from "@/lib/format";

const ICONS = {
  deals: Briefcase,
  deposits: Wallet,
  system: Bell,
} as const;

const TITLES = {
  deals: "Сделки",
  deposits: "Депозиты",
  system: "Системные",
} as const;

/**
 * Notification detail page.
 *
 * Renders the title/body/timestamp + any deep links we can infer from the
 * notification payload or body (e.g. references like ``#42`` for a deal).
 * Marks the notification as read on first successful load so the inbox
 * badge clears even if the user opened the link directly without
 * swiping the row.
 */
export default function NotificationDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const numericId = Number(id);
  const { data, isLoading, isError } = useNotification(
    Number.isFinite(numericId) ? numericId : undefined,
  );
  const markRead = useMarkNotificationRead();

  useEffect(() => {
    if (data && !data.is_read) {
      markRead.mutate(data.id);
    }
  }, [data, markRead]);

  const dealRef = useMemo(() => {
    if (!data) return null;
    const payloadId =
      typeof data.payload === "object" && data.payload && "deal_id" in data.payload
        ? Number((data.payload as { deal_id: unknown }).deal_id)
        : NaN;
    if (Number.isFinite(payloadId) && payloadId > 0) return payloadId;
    const match = /#(\d+)/.exec(data.body || "");
    return match ? Number(match[1]) : null;
  }, [data]);

  if (isLoading) {
    return (
      <Page showBack>
        <div className="px-4 pt-3 space-y-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-24" />
        </div>
      </Page>
    );
  }

  if (isError || !data) {
    return (
      <Page showBack>
        <Header title="Уведомление" />
        <div className="px-4">
          <EmptyState
            title="Уведомление не найдено"
            description="Возможно, оно было удалено или принадлежит другому пользователю."
          />
        </div>
      </Page>
    );
  }

  const Icon = (ICONS as Record<string, typeof Bell>)[data.type] ?? Bell;
  const typeLabel = (TITLES as Record<string, string>)[data.type] ?? "Системные";

  return (
    <Page showBack>
      <div className="px-4 pt-1 pb-4">
        <button
          type="button"
          onClick={() => navigate("/notifications")}
          aria-label="К оповещениям"
          className="text-text-muted text-sm flex items-center gap-1 mb-2"
        >
          <ArrowLeft className="size-4" /> К оповещениям
        </button>

        <div className="bg-panel rounded-card p-4 space-y-3">
          <div className="flex items-center gap-3">
            <div className="size-10 grid place-items-center rounded-full bg-accent/15 text-accent shrink-0">
              <Icon className="size-5" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs uppercase tracking-wide text-text-muted">{typeLabel}</div>
              <div className="font-semibold leading-tight truncate">{data.title}</div>
              <div className="text-xs text-text-muted mt-0.5">
                {relativeTime(data.created_at)}
              </div>
            </div>
          </div>

          {data.body && (
            <div className="text-sm whitespace-pre-line border-t border-border pt-3">
              {data.body}
            </div>
          )}
        </div>

        {dealRef !== null && (
          <Button
            variant="primary"
            fullWidth
            className="mt-3"
            onClick={() => navigate(`/deals/${dealRef}`)}
          >
            <ExternalLink className="size-4" /> Открыть сделку #{dealRef}
          </Button>
        )}

        {data.type === "deposits" && (
          <Button
            variant="secondary"
            fullWidth
            className="mt-2"
            onClick={() => navigate("/wallet")}
          >
            <Wallet className="size-4" /> Открыть кошелёк
          </Button>
        )}
      </div>
    </Page>
  );
}
