/**
 * Continental admin "edit on behalf of user" sections.
 *
 * These render under the user detail page and let the admin manage:
 *   * The user's services (title/description/price/deposit/rating/...)
 *   * Reviews received by the user (edit + delete)
 *   * Comments written by the user (edit + delete)
 *
 * Each section uses optimistic UI patterns from the rest of the admin
 * panel (Sheet-driven editor, mutations invalidate the per-section
 * query cache, toasts on success/error).
 */
import { useEffect, useState } from "react";
import {
  Edit2,
  MessageSquare,
  Plus,
  Star,
  Trash2,
  Briefcase,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Sheet } from "@/components/ui/Sheet";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { confirmDialog } from "@/lib/dialog";
import { UserPicker } from "@/components/domain/UserPicker";
import {
  useAdminCreateReview,
  useAdminDeleteComment,
  useAdminDeleteReview,
  useAdminDeleteService,
  useAdminUpdateComment,
  useAdminUpdateReview,
  useAdminUpdateService,
  useAdminUserComments,
  useAdminUserReviews,
  useAdminUserServices,
} from "@/api/admin/hooks";
import type {
  AdminCommentItemDto,
  AdminReviewItemDto,
  AdminServiceItemDto,
  UserCardDto,
} from "@/api/types";

interface SectionProps {
  userId: number;
}

// ── Services ──────────────────────────────────────────────────────────────

export function ServicesSection({ userId }: SectionProps) {
  const { data, isLoading } = useAdminUserServices(userId);
  const [editing, setEditing] = useState<AdminServiceItemDto | null>(null);

  return (
    <section className="bg-panel rounded-card p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
          <Briefcase size={14} /> Услуги
          {data && <span className="text-text">({data.length})</span>}
        </h3>
      </div>
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : !data || data.length === 0 ? (
        <p className="text-sm text-text-muted py-2">Нет услуг.</p>
      ) : (
        <ul className="space-y-2">
            {data.map((s, _idx) => (
              <li
                key={s.id}
                className="bg-panel-2 rounded-card p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{s.title}</div>
                    <div className="text-xs text-text-muted line-clamp-2">{s.description}</div>
                    <div className="mt-1 text-[11px] text-text-muted flex items-center gap-2 flex-wrap">
                      <span>{s.price.toFixed(2)} $</span>
                      <span>·</span>
                      <span>{s.status}</span>
                      <span>·</span>
                      <span>{s.deals_count} сделок</span>
                      {s.rating_manual !== null && (
                        <>
                          <span>·</span>
                          <span className="flex items-center gap-0.5">
                            <Star size={10} className="text-accent" /> {s.rating_manual}
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setEditing(s)}
                    className="p-1.5 rounded-button bg-panel hover:bg-panel-2 active:scale-95"
                    aria-label="Изменить"
                  >
                    <Edit2 size={14} />
                  </button>
                </div>
              </li>
            ))}
        </ul>
      )}
      <ServiceEditSheet userId={userId} service={editing} onClose={() => setEditing(null)} />
    </section>
  );
}

function ServiceEditSheet({
  userId,
  service,
  onClose,
}: {
  userId: number;
  service: AdminServiceItemDto | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const update = useAdminUpdateService(userId);
  const del = useAdminDeleteService(userId);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [price, setPrice] = useState("");
  const [deposit, setDeposit] = useState("");
  const [views, setViews] = useState("");
  const [dealsCount, setDealsCount] = useState("");
  const [ratingManual, setRatingManual] = useState("");
  const [status, setStatus] = useState("active");

  // Seed inputs when the sheet opens (re-seed each time it (re)opens with
  // a different service).
  useEffect(() => {
    if (!service) return;
    setTitle(service.title);
    setDescription(service.description);
    setPrice(String(service.price));
    setDeposit(String(service.deposit));
    setViews(String(service.views));
    setDealsCount(String(service.deals_count));
    setRatingManual(service.rating_manual !== null ? String(service.rating_manual) : "");
    setStatus(service.status);
  }, [service]);

  const reset = () => {
    setTitle("");
    setDescription("");
    setPrice("");
    setDeposit("");
    setViews("");
    setDealsCount("");
    setRatingManual("");
    setStatus("active");
  };

  const close = () => {
    reset();
    onClose();
  };

  const save = async () => {
    if (!service) return;
    try {
      const body: Record<string, unknown> = {};
      if (title !== service.title) body.title = title;
      if (description !== service.description) body.description = description;
      if (Number(price) !== service.price) body.price = Number(price);
      if (Number(deposit) !== service.deposit) body.deposit = Number(deposit);
      if (Number(views) !== service.views) body.views = Number(views);
      if (Number(dealsCount) !== service.deals_count) body.deals_count = Number(dealsCount);
      if (ratingManual === "") {
        if (service.rating_manual !== null) body.clear_rating = true;
      } else if (Number(ratingManual) !== service.rating_manual) {
        body.rating_manual = Number(ratingManual);
      }
      if (status !== service.status) body.status = status;
      if (Object.keys(body).length === 0) {
        toast.show({ kind: "info", title: "Нет изменений" });
        close();
        return;
      }
      await update.mutateAsync({ serviceId: service.id, body });
      toast.show({ kind: "success", title: "Услуга обновлена" });
      close();
    } catch (e: unknown) {
      toast.show({ kind: "error", title: "Ошибка", body: (e as Error)?.message ?? "" });
    }
  };

  const onDelete = async () => {
    if (!service) return;
    // Audit L-15 — ``confirmDialog`` prefers ``Telegram.WebApp.showConfirm``.
    if (!(await confirmDialog("Удалить услугу?"))) return;
    try {
      await del.mutateAsync(service.id);
      toast.show({ kind: "success", title: "Услуга удалена" });
      close();
    } catch (e: unknown) {
      toast.show({ kind: "error", title: "Ошибка", body: (e as Error)?.message ?? "" });
    }
  };

  return (
    <Sheet open={!!service} onClose={close} title={service?.title ?? "Услуга"}>
      <div className="space-y-3">
        <Input label="Заголовок" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Textarea label="Описание" value={description} onChange={(e) => setDescription(e.target.value)} />
        <div className="grid grid-cols-2 gap-3">
          <Input
            label="Цена $"
            type="number"
            inputMode="decimal"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
          />
          <Input
            label="Депозит $"
            type="number"
            inputMode="decimal"
            value={deposit}
            onChange={(e) => setDeposit(e.target.value)}
          />
          <Input
            label="Просмотры"
            type="number"
            inputMode="numeric"
            value={views}
            onChange={(e) => setViews(e.target.value)}
          />
          <Input
            label="Сделок"
            type="number"
            inputMode="numeric"
            value={dealsCount}
            onChange={(e) => setDealsCount(e.target.value)}
          />
          <Input
            label="Рейтинг 0..5 (пусто = сброс)"
            type="number"
            inputMode="decimal"
            value={ratingManual}
            onChange={(e) => setRatingManual(e.target.value)}
          />
          <label className="block">
            <div className="mb-1 text-[14px] font-medium text-text">Статус</div>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="h-11 w-full px-3 rounded-button bg-panel text-text"
            >
              <option value="draft">draft</option>
              <option value="active">active</option>
              <option value="paused">paused</option>
              <option value="banned">banned</option>
            </select>
          </label>
        </div>
        <div className="flex gap-2 pt-2">
          <Button variant="danger" onClick={onDelete} disabled={del.isPending}>
            <Trash2 size={14} />
          </Button>
          <Button variant="secondary" fullWidth onClick={close}>
            Отмена
          </Button>
          <Button fullWidth onClick={save} disabled={update.isPending}>
            Сохранить
          </Button>
        </div>
      </div>
    </Sheet>
  );
}

// ── Reviews ──────────────────────────────────────────────────────────────

export function ReviewsSection({ userId }: SectionProps) {
  const [direction, setDirection] = useState<"received" | "written">("received");
  const { data, isLoading } = useAdminUserReviews(userId, direction);
  const [editing, setEditing] = useState<AdminReviewItemDto | null>(null);
  const [creating, setCreating] = useState(false);

  return (
    <section className="bg-panel rounded-card p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
          <Star size={14} /> Отзывы
          {data && <span className="text-text">({data.length})</span>}
        </h3>
        <div className="flex gap-1">
          <ToggleButton
            active={direction === "received"}
            onClick={() => setDirection("received")}
            label="Получено"
          />
          <ToggleButton
            active={direction === "written"}
            onClick={() => setDirection("written")}
            label="Написано"
          />
        </div>
      </div>
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon={<Star size={20} />}
          title={direction === "received" ? "Отзывов нет" : "Юзер не оставлял отзывов"}
        />
      ) : (
        <ul className="space-y-2">
            {data.map((r, _idx) => (
              <li
                key={r.id}
                className="bg-panel-2 rounded-card p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] uppercase tracking-wide text-text-muted">
                      @{r.author_username ?? "—"} → @{r.target_username ?? "—"} · {r.rating}/5
                    </div>
                    <div className="mt-1 text-sm">{r.text}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setEditing(r)}
                    className="p-1.5 rounded-button bg-panel hover:bg-panel-2 active:scale-95"
                    aria-label="Изменить"
                  >
                    <Edit2 size={14} />
                  </button>
                </div>
              </li>
            ))}
        </ul>
      )}
      <Button
        variant="secondary"
        fullWidth
        className="mt-3"
        onClick={() => setCreating(true)}
      >
        <Plus size={14} /> Добавить отзыв
      </Button>
      <ReviewEditSheet userId={userId} review={editing} onClose={() => setEditing(null)} />
      <ReviewCreateSheet userId={userId} open={creating} onClose={() => setCreating(false)} />
    </section>
  );
}

function ReviewCreateSheet({
  userId,
  open,
  onClose,
}: {
  userId: number;
  open: boolean;
  onClose: () => void;
}) {
  const toast = useToast();
  const create = useAdminCreateReview(userId);
  const [author, setAuthor] = useState<UserCardDto | null>(null);
  const [rating, setRating] = useState("5");
  const [text, setText] = useState("");

  const close = () => {
    setAuthor(null);
    setRating("5");
    setText("");
    onClose();
  };

  const submit = async () => {
    const r = Number(rating);
    if (!Number.isFinite(r) || r < 0 || r > 5) {
      toast.show({ kind: "error", title: "Рейтинг 0..5" });
      return;
    }
    if (!author) {
      toast.show({ kind: "error", title: "Выберите автора" });
      return;
    }
    try {
      await create.mutateAsync({
        author_id: author.id,
        target_id: userId,
        rating: r,
        text,
      });
      toast.show({ kind: "success", title: "Отзыв создан" });
      close();
    } catch (e: unknown) {
      toast.show({ kind: "error", title: "Ошибка", body: (e as Error)?.message ?? "" });
    }
  };

  return (
    <Sheet open={open} onClose={close} title="Новый отзыв">
      <div className="space-y-3">
        <UserPicker
          label="Автор"
          placeholder="@buyer1"
          value={author?.username ?? ""}
          onChange={() => {
            /* selection is driven by onPick — the bare username text
             * isn't enough to submit the review (we need the picked
             * user's numeric id), so we intentionally ignore raw
             * keystrokes here. */
          }}
          onPick={setAuthor}
        />
        <Input
          label="Рейтинг 0..5"
          type="number"
          inputMode="decimal"
          value={rating}
          onChange={(e) => setRating(e.target.value)}
        />
        <Textarea label="Текст" value={text} onChange={(e) => setText(e.target.value)} />
        <div className="flex gap-2">
          <Button variant="secondary" fullWidth onClick={close}>
            Отмена
          </Button>
          <Button fullWidth onClick={submit} disabled={create.isPending}>
            Создать
          </Button>
        </div>
      </div>
    </Sheet>
  );
}

function ReviewEditSheet({
  userId,
  review,
  onClose,
}: {
  userId: number;
  review: AdminReviewItemDto | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const update = useAdminUpdateReview(userId);
  const del = useAdminDeleteReview(userId);
  const [rating, setRating] = useState("");
  const [text, setText] = useState("");

  useEffect(() => {
    if (!review) return;
    setRating(String(review.rating));
    setText(review.text);
  }, [review]);

  const close = () => {
    setRating("");
    setText("");
    onClose();
  };

  const save = async () => {
    if (!review) return;
    const r = Number(rating);
    if (!Number.isFinite(r) || r < 0 || r > 5) {
      toast.show({ kind: "error", title: "Рейтинг 0..5" });
      return;
    }
    try {
      await update.mutateAsync({ reviewId: review.id, body: { rating: r, text } });
      toast.show({ kind: "success", title: "Отзыв обновлён" });
      close();
    } catch (e: unknown) {
      toast.show({ kind: "error", title: "Ошибка", body: (e as Error)?.message ?? "" });
    }
  };

  const onDelete = async () => {
    if (!review) return;
    // Audit L-15 — ``confirmDialog`` prefers ``Telegram.WebApp.showConfirm``.
    if (!(await confirmDialog("Удалить отзыв?"))) return;
    try {
      await del.mutateAsync(review.id);
      toast.show({ kind: "success", title: "Отзыв удалён" });
      close();
    } catch (e: unknown) {
      toast.show({ kind: "error", title: "Ошибка", body: (e as Error)?.message ?? "" });
    }
  };

  return (
    <Sheet open={!!review} onClose={close} title="Отзыв">
      <div className="space-y-3">
        <Input
          label="Рейтинг 0..5"
          type="number"
          inputMode="decimal"
          value={rating}
          onChange={(e) => setRating(e.target.value)}
        />
        <Textarea label="Текст" value={text} onChange={(e) => setText(e.target.value)} />
        <div className="flex gap-2 pt-2">
          <Button variant="danger" onClick={onDelete} disabled={del.isPending}>
            <Trash2 size={14} />
          </Button>
          <Button variant="secondary" fullWidth onClick={close}>
            Отмена
          </Button>
          <Button fullWidth onClick={save} disabled={update.isPending}>
            Сохранить
          </Button>
        </div>
      </div>
    </Sheet>
  );
}

// ── Comments ──────────────────────────────────────────────────────────────

export function CommentsSection({ userId }: SectionProps) {
  const { data, isLoading } = useAdminUserComments(userId);
  const [editing, setEditing] = useState<AdminCommentItemDto | null>(null);

  return (
    <section className="bg-panel rounded-card p-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-text-muted flex items-center gap-1.5">
          <MessageSquare size={14} /> Комментарии
          {data && <span className="text-text">({data.length})</span>}
        </h3>
      </div>
      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-12" />
        </div>
      ) : !data || data.length === 0 ? (
        <p className="text-sm text-text-muted py-2">Юзер не оставлял комментариев.</p>
      ) : (
        <ul className="space-y-2">
            {data.map((c, _idx) => (
              <li
                key={c.id}
                className="bg-panel-2 rounded-card p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] uppercase tracking-wide text-text-muted">
                      В услуге #{c.service_id}
                      {c.rating !== null && ` · ${c.rating}/5`}
                    </div>
                    <div className="mt-1 text-sm">{c.text}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setEditing(c)}
                    className="p-1.5 rounded-button bg-panel hover:bg-panel-2 active:scale-95"
                    aria-label="Изменить"
                  >
                    <Edit2 size={14} />
                  </button>
                </div>
              </li>
            ))}
        </ul>
      )}
      <CommentEditSheet userId={userId} comment={editing} onClose={() => setEditing(null)} />
    </section>
  );
}

function CommentEditSheet({
  userId,
  comment,
  onClose,
}: {
  userId: number;
  comment: AdminCommentItemDto | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const update = useAdminUpdateComment(userId);
  const del = useAdminDeleteComment(userId);
  const [text, setText] = useState("");
  const [rating, setRating] = useState("");

  useEffect(() => {
    if (!comment) return;
    setText(comment.text);
    setRating(comment.rating !== null ? String(comment.rating) : "");
  }, [comment]);

  const close = () => {
    setText("");
    setRating("");
    onClose();
  };

  const save = async () => {
    if (!comment) return;
    try {
      const body: Record<string, unknown> = {};
      if (text !== comment.text) body.text = text;
      if (rating === "") {
        if (comment.rating !== null) body.clear_rating = true;
      } else {
        const r = Number(rating);
        if (!Number.isFinite(r) || r < 0 || r > 5) {
          toast.show({ kind: "error", title: "Рейтинг 0..5" });
          return;
        }
        if (r !== comment.rating) body.rating = r;
      }
      if (Object.keys(body).length === 0) {
        close();
        return;
      }
      await update.mutateAsync({ commentId: comment.id, body });
      toast.show({ kind: "success", title: "Комментарий обновлён" });
      close();
    } catch (e: unknown) {
      toast.show({ kind: "error", title: "Ошибка", body: (e as Error)?.message ?? "" });
    }
  };

  const onDelete = async () => {
    if (!comment) return;
    // Audit L-15 — ``confirmDialog`` prefers ``Telegram.WebApp.showConfirm``.
    if (!(await confirmDialog("Удалить комментарий?"))) return;
    try {
      await del.mutateAsync(comment.id);
      toast.show({ kind: "success", title: "Комментарий удалён" });
      close();
    } catch (e: unknown) {
      toast.show({ kind: "error", title: "Ошибка", body: (e as Error)?.message ?? "" });
    }
  };

  return (
    <Sheet open={!!comment} onClose={close} title="Комментарий">
      <div className="space-y-3">
        <Textarea label="Текст" value={text} onChange={(e) => setText(e.target.value)} />
        <Input
          label="Рейтинг 0..5 (пусто = сброс)"
          type="number"
          inputMode="decimal"
          value={rating}
          onChange={(e) => setRating(e.target.value)}
        />
        <div className="flex gap-2 pt-2">
          <Button variant="danger" onClick={onDelete} disabled={del.isPending}>
            <Trash2 size={14} />
          </Button>
          <Button variant="secondary" fullWidth onClick={close}>
            Отмена
          </Button>
          <Button fullWidth onClick={save} disabled={update.isPending}>
            Сохранить
          </Button>
        </div>
      </div>
    </Sheet>
  );
}

function ToggleButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-xs px-2 py-1 rounded-button transition-colors ${
        active ? "bg-accent text-black" : "bg-panel-2 text-text-muted"
      }`}
    >
      {label}
    </button>
  );
}
