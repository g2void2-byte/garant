import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { HandCoins, MessageSquare, Star, Trash2 } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Textarea";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  buildServiceCommentsSearchParams,
  useCreateServiceComment,
  useDeleteServiceComment,
  useMe,
  useServiceComments,
  useServiceDetail,
} from "@/api/hooks";
import { api } from "@/api/client";
import type { ServiceCommentDto, ServiceDetailDto } from "@/api/types";
import { dealsLabel, formatMoney, formatRatingValue, relativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";
import { openTelegramLink } from "@/lib/tg";
import { buildTelegramUserUrl } from "@/lib/telegramLinks";
import { parsePositiveIntRouteParam } from "@/lib/routeParams";
import { safeMediaUrl } from "@/lib/mediaLinks";
import { createDealPath, normalizeUsernameRef, userProfilePath } from "@/lib/usernames";

const SERVICE_COMMENTS_PAGE_SIZE = 50;

export default function ServiceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const serviceId = parsePositiveIntRouteParam(id);
  const { data: service, isError, isLoading } = useServiceDetail(serviceId);
  const firstCommentsParams = useMemo(
    () => ({ limit: SERVICE_COMMENTS_PAGE_SIZE, offset: 0 }),
    [],
  );
  const { data: comments } = useServiceComments(serviceId, firstCommentsParams);
  const { data: me } = useMe();
  const [commentItems, setCommentItems] = useState<ServiceCommentDto[]>([]);
  const [commentsReachedEnd, setCommentsReachedEnd] = useState(false);
  const [loadingMoreComments, setLoadingMoreComments] = useState(false);
  const [commentsError, setCommentsError] = useState<string | null>(null);

  useEffect(() => {
    const page = comments ?? [];
    setCommentItems(page);
    setCommentsReachedEnd(page.length < SERVICE_COMMENTS_PAGE_SIZE);
    setCommentsError(null);
  }, [comments, serviceId]);

  const loadMoreComments = async () => {
    if (!serviceId || loadingMoreComments || commentsReachedEnd) return;
    setLoadingMoreComments(true);
    setCommentsError(null);
    try {
      const page = await api
        .get(`api/services/${serviceId}/comments`, {
          searchParams: buildServiceCommentsSearchParams({
            limit: SERVICE_COMMENTS_PAGE_SIZE,
            offset: commentItems.length,
          }),
        })
        .json<ServiceCommentDto[]>();
      setCommentItems((prev) => [...prev, ...page]);
      if (page.length < SERVICE_COMMENTS_PAGE_SIZE) setCommentsReachedEnd(true);
    } catch (e: unknown) {
      setCommentsError((e as Error)?.message || "Не удалось загрузить еще комментарии");
    } finally {
      setLoadingMoreComments(false);
    }
  };

  if (!serviceId || isError) {
    return (
      <Page showBack>
        <Header title="Услуга" />
        <div className="px-4">
          <EmptyState
            title="Услуга не найдена"
            description="Проверьте ссылку или вернитесь к каталогу."
          />
        </div>
      </Page>
    );
  }

  if (isLoading) {
    return (
      <Page showBack>
        <Header title="Услуга" />
        <div className="px-4 space-y-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-20" />
          <Skeleton className="h-40" />
        </div>
      </Page>
    );
  }

  if (!service) {
    return (
      <Page showBack>
        <Header title="Услуга" />
        <div className="px-4">
          <EmptyState title="Услуга не найдена" />
        </div>
      </Page>
    );
  }

  return (
    <Page showBack>
      <Header title="Услуга" />
      <div className="px-4 space-y-3">
        <ServiceHeroCard service={service} />
        <ServicePhotoGallery photos={service.photo_urls ?? []} />
        <OwnerActions service={service} myUsername={me?.username} />
        <ServiceStatsRow service={service} />
        {service.description && <ServiceDescription text={service.description} />}
        <CommentsSection
          serviceId={serviceId}
          comments={commentItems}
          hasMore={
            !commentsReachedEnd &&
            commentItems.length >= SERVICE_COMMENTS_PAGE_SIZE &&
            commentItems.length < service.comments_count
          }
          loadingMore={loadingMoreComments}
          loadMoreError={commentsError}
          onLoadMore={loadMoreComments}
          isOwner={service.owner?.username === me?.username}
          myId={me?.id}
          isAdmin={Boolean(me?.admin && me.admin > 0)}
        />
      </div>
    </Page>
  );
}

function ServicePhotoGallery({ photos }: { photos: string[] }) {
  const safePhotos = photos
    .map((url) => safeMediaUrl(url))
    .filter((url): url is string => Boolean(url));
  if (!safePhotos.length) return null;
  return (
    <div className="-mx-4 px-4 flex gap-2 overflow-x-auto snap-x snap-mandatory pb-1">
      {safePhotos.map((url, i) => (
        <div
          key={`${url}-${i}`}
          className="shrink-0 w-[78%] aspect-[4/3] rounded-card overflow-hidden bg-panel-2 snap-center border border-border"
        >
          <img src={url} alt="" className="size-full object-cover" />
        </div>
      ))}
    </div>
  );
}

function ServiceHeroCard({ service }: { service: ServiceDetailDto }) {
  const rating = service.rating_avg !== null ? formatRatingValue(service.rating_avg) : null;
  return (
    <Card className="p-0 overflow-hidden">
      <div className="relative h-32 bg-gradient-to-br from-accent/30 via-panel-2 to-panel flex items-center justify-center">
        <div className="text-5xl font-black opacity-30 select-none">
          {service.category.name.slice(0, 1).toUpperCase()}
        </div>
        <div className="absolute top-2 left-3 text-[11px] uppercase tracking-wider text-text-muted">
          {service.category.name}
        </div>
        {rating && (
          <div className="absolute top-2 right-3 inline-flex items-center gap-1 rounded-full bg-accent text-accent-fg px-2 py-0.5 text-xs font-bold">
            <Star className="size-3 fill-current" />
            {rating}
          </div>
        )}
      </div>
      <div className="p-4">
        <h2 className="text-xl font-bold leading-tight">{service.title}</h2>
        <div className="mt-1 text-accent text-lg font-bold">
          {formatMoney(service.price)}
        </div>
      </div>
    </Card>
  );
}

function OwnerActions({
  service,
  myUsername,
}: {
  service: ServiceDetailDto;
  myUsername?: string | null;
}) {
  const navigate = useNavigate();
  const owner = service.owner;
  if (!owner) return null;
  const ownerUsername = normalizeUsernameRef(owner.username);
  const ownerProfilePath = userProfilePath(ownerUsername);
  const ownerDealPath = createDealPath(ownerUsername);
  const ownerTelegramUrl = buildTelegramUserUrl(ownerUsername);
  const isSelf = ownerUsername === normalizeUsernameRef(myUsername);
  const ownerName = owner.display_name || ownerUsername || "Владелец";
  const ownerMeta = ownerUsername
    ? `@${ownerUsername} · ${dealsLabel(owner.deals_count)}`
    : `Профиль недоступен · ${dealsLabel(owner.deals_count)}`;
  const ownerInfo = (
    <>
      <Avatar name={ownerName} src={owner.photo_url} size={48} />
      <div className="min-w-0">
        <div className="font-semibold truncate">{ownerName}</div>
        <div className="text-xs text-text-muted truncate">{ownerMeta}</div>
      </div>
    </>
  );
  return (
    <Card className="p-3">
      <div className="flex items-center gap-3">
        {ownerProfilePath ? (
          <Link
            to={ownerProfilePath}
            className="flex items-center gap-3 min-w-0 flex-1"
          >
            {ownerInfo}
          </Link>
        ) : (
          <div className="flex items-center gap-3 min-w-0 flex-1">{ownerInfo}</div>
        )}
      </div>
      {!isSelf && ownerDealPath && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Button
            variant="primary"
            size="md"
            onClick={() => navigate(ownerDealPath)}
          >
            <HandCoins className="size-4" /> Сделка
          </Button>
          <Button
            variant="secondary"
            size="md"
            disabled={!ownerTelegramUrl}
            onClick={() => ownerTelegramUrl && openTelegramLink(ownerTelegramUrl)}
          >
            <MessageSquare className="size-4" /> Написать
          </Button>
        </div>
      )}
    </Card>
  );
}

function ServiceStatsRow({ service }: { service: ServiceDetailDto }) {
  const items = [
    {
      label: "Рейтинг",
      value:
        service.rating_avg !== null ? formatRatingValue(service.rating_avg) : "—",
      hint: service.rating_count
        ? `${service.rating_count} оценок`
        : "нет оценок",
    },
    {
      label: "Комментарии",
      value: String(service.comments_count),
      hint: service.comments_count ? "за всё время" : "пока пусто",
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-2">
      {items.map((it) => (
        <Card key={it.label} className="p-3">
          <div className="text-[11px] uppercase tracking-wider text-text-muted">
            {it.label}
          </div>
          <div className="mt-1 text-2xl font-bold leading-tight">{it.value}</div>
          <div className="text-xs text-text-muted">{it.hint}</div>
        </Card>
      ))}
    </div>
  );
}

function ServiceDescription({ text }: { text: string }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] uppercase tracking-wider text-text-muted">
        Описание
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{text}</p>
    </Card>
  );
}

function CommentsSection({
  serviceId,
  comments,
  hasMore,
  loadingMore,
  loadMoreError,
  onLoadMore,
  isOwner,
  myId,
  isAdmin,
}: {
  serviceId: number;
  comments: ServiceCommentDto[];
  hasMore: boolean;
  loadingMore: boolean;
  loadMoreError: string | null;
  onLoadMore: () => void;
  isOwner: boolean;
  myId?: number;
  isAdmin: boolean;
}) {
  return (
    <div className="space-y-2">
      <div className="text-[11px] uppercase tracking-wider text-text-muted px-1">
        Комментарии
      </div>
      {!isOwner && <CommentComposer serviceId={serviceId} />}
      {comments.length === 0 ? (
        <EmptyState
          icon={<MessageSquare className="size-5" />}
          title="Пока нет комментариев"
          description="Будьте первым, кто оставит отзыв об услуге."
        />
      ) : (
        comments.map((c) => (
          <CommentRow
            key={c.id}
            serviceId={serviceId}
            comment={c}
            canDelete={Boolean(
              myId === c.author_id || isOwner || isAdmin,
            )}
          />
        ))
      )}
      {hasMore && (
        <Button onClick={onLoadMore} disabled={loadingMore} className="w-full">
          {loadingMore ? "Загружаю..." : "Показать еще"}
        </Button>
      )}
      {loadMoreError && <div className="text-xs text-danger text-center">{loadMoreError}</div>}
    </div>
  );
}

function CommentComposer({ serviceId }: { serviceId: number }) {
  const [rating, setRating] = useState<number | null>(null);
  const [text, setText] = useState("");
  const create = useCreateServiceComment(serviceId);

  const canSubmit = useMemo(
    () => (text.trim().length > 0 || rating !== null) && !create.isPending,
    [text, rating, create.isPending],
  );
  const errMsg = useMemo(() => {
    const err = create.error as { response?: { status?: number } } | null;
    if (!err) return null;
    if (err.response?.status === 400) return "Нельзя оставлять комментарий к своей услуге";
    return "Не удалось отправить комментарий";
  }, [create.error]);

  return (
    <Card className="p-3">
      <div className="text-[11px] uppercase tracking-wider text-text-muted">
        Ваш отзыв
      </div>
      <div className="mt-2 flex items-center gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => setRating(rating === n ? null : n)}
            className={cn(
              "size-8 grid place-items-center rounded-button transition-colors",
              rating !== null && n <= rating
                ? "text-accent"
                : "text-text-muted hover:text-text",
            )}
            aria-label={`${n} из 5`}
          >
            <Star
              className={cn(
                "size-5",
                rating !== null && n <= rating && "fill-current",
              )}
            />
          </button>
        ))}
        {rating !== null && (
          <button
            type="button"
            onClick={() => setRating(null)}
            className="ml-2 text-xs text-text-muted hover:text-text"
          >
            Сбросить
          </button>
        )}
      </div>
      <div className="mt-3">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Поделитесь впечатлением..."
          rows={3}
          className="!min-h-[88px]"
        />
      </div>
      {errMsg && <div className="mt-2 text-xs text-danger">{errMsg}</div>}
      <div className="mt-3 flex justify-end">
        <Button
          variant="primary"
          size="md"
          disabled={!canSubmit}
          onClick={() => {
            create.mutate(
              { text: text.trim(), rating },
              {
                onSuccess: () => {
                  setText("");
                  setRating(null);
                },
              },
            );
          }}
        >
          Отправить
        </Button>
      </div>
    </Card>
  );
}

function CommentRow({
  serviceId,
  comment: rawComment,
  canDelete,
}: {
  serviceId: number;
  comment: ServiceCommentDto;
  canDelete: boolean;
}) {
  const del = useDeleteServiceComment(serviceId);
  const comment = {
    ...rawComment,
    author_username: normalizeUsernameRef(rawComment.author_username),
  };
  const authorPath = userProfilePath(comment.author_username);
  return (
    <Card className="p-3">
      <div className="flex items-start gap-3">
        <Avatar
          name={comment.author_display_name || comment.author_username || "?"}
          src={comment.author_photo_url}
          size={36}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Link
              to={authorPath ?? "#"}
              className="font-semibold text-sm truncate hover:text-accent"
            >
              {comment.author_display_name || comment.author_username || "—"}
            </Link>
            {comment.rating !== null && (
              <span className="inline-flex items-center gap-0.5 text-accent text-xs font-bold">
                <Star className="size-3 fill-current" />
                {comment.rating}
              </span>
            )}
            <span className="ml-auto text-[11px] text-text-muted">
              {relativeTime(comment.created_at)}
            </span>
          </div>
          {comment.text && (
            <div className="mt-1 text-sm whitespace-pre-wrap break-words">
              {comment.text}
            </div>
          )}
        </div>
        {canDelete && (
          <button
            type="button"
            onClick={() => del.mutate(comment.id)}
            disabled={del.isPending}
            className="text-text-muted hover:text-danger p-1 -mr-1"
            aria-label="Удалить"
          >
            <Trash2 className="size-4" />
          </button>
        )}
      </div>
    </Card>
  );
}
