import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Send, Trash2, Users } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Switch } from "@/components/ui/Switch";
import { useToast } from "@/components/ui/Toast";
import { confirmDialog } from "@/lib/dialog";
import {
  useAdminBroadcastPreview,
  useAdminBroadcasts,
  useAdminCreateBroadcast,
  useAdminDeleteBroadcast,
} from "@/api/admin/hooks";
import type { AdminBroadcastCreateBody } from "@/api/types";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";
import { formatAdminCount, getAdminTotalPages, shouldShowAdminPagination } from "./format";

const ROLES: Array<{ value: "" | "admin" | "arbiter" | "vip" | "regular"; label: string }> = [
  { value: "", label: "Все" },
  { value: "admin", label: "Админы" },
  { value: "arbiter", label: "Арбитры" },
  { value: "vip", label: "VIP" },
  { value: "regular", label: "Обычные" },
];
const PAGE_SIZE = 50;

export default function AdminBroadcastsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const { data, isLoading } = useAdminBroadcasts({ page, page_size: PAGE_SIZE });
  const del = useAdminDeleteBroadcast();
  const toast = useToast();
  const [composerOpen, setComposerOpen] = useState(false);

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader
        title="Рассылки"
        subtitle={data ? `${formatAdminCount(data.total)} всего` : undefined}
        right={
          <button
            type="button"
            onClick={() => setComposerOpen(true)}
            className="rounded-button bg-accent text-accent-fg px-3 py-1.5 text-sm font-medium active:scale-95"
          >
            Новая
          </button>
        }
      />
      <div className="px-4 space-y-2 pb-24">
        {isLoading ? (
          Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-card" />
          ))
        ) : data?.items.length === 0 ? (
          <p className="text-sm text-text-muted text-center py-12">Рассылок нет</p>
        ) : (
          data?.items.map((b, _idx) => (
            <div
              key={b.id}
              className="bg-panel rounded-card p-3"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  {b.title && <div className="font-medium truncate">{b.title}</div>}
                  <div className="text-sm text-text-muted line-clamp-2">{b.body}</div>
                  <div className="text-[11px] text-text-muted mt-1 flex items-center gap-2">
                    <Users size={11} /> {formatAdminCount(b.total_recipients)} получателей · доставлено{" "}
                    {formatAdminCount(b.delivered_count)}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={async () => {
                    // Audit L-15 — ``confirmDialog`` prefers Telegram’s native
                    // ``showConfirm``; falls back to ``window.confirm`` outside Telegram.
                    if (!(await confirmDialog("Удалить рассылку из истории?"))) return;
                    try {
                      await del.mutateAsync(b.id);
                      toast.show({ kind: "info", title: "Удалено" });
                    } catch (e) {
                      toast.show({
                        kind: "error",
                        title: "Ошибка",
                        body: (e as Error).message,
                      });
                    }
                  }}
                  className="text-danger active:scale-90"
                  aria-label="Удалить"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>
      {data && shouldShowAdminPagination(data.total, data.page_size) && (
        <Pagination
          page={page}
          totalPages={getAdminTotalPages(data.total, data.page_size)}
          onPage={setPage}
        />
      )}

      <Sheet
        open={composerOpen}
        onClose={() => setComposerOpen(false)}
        title="Новая рассылка"
      >
        <Composer onClose={() => setComposerOpen(false)} />
      </Sheet>
    </Page>
  );
}

function Pagination({
  page,
  totalPages,
  onPage,
}: {
  page: number;
  totalPages: number;
  onPage: (page: number) => void;
}) {
  return (
    <div className="flex items-center justify-center gap-3 mt-1 mb-4 text-sm">
      <button
        type="button"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
        className="p-2 rounded-button bg-panel disabled:opacity-40 active:scale-95"
        aria-label={"\u041d\u0430\u0437\u0430\u0434"}
      >
        <ChevronLeft size={18} />
      </button>
      <span className="text-text-muted">
        {page} / {totalPages}
      </span>
      <button
        type="button"
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
        className="p-2 rounded-button bg-panel disabled:opacity-40 active:scale-95"
        aria-label={"\u0412\u043f\u0435\u0440\u0451\u0434"}
      >
        <ChevronRight size={18} />
      </button>
    </div>
  );
}

// Mirrors the backend ``AdminBroadcastCreateIn`` field validators
// (``schemas.py``). Keep these in sync so the live UI counter and
// inline deeplink error match what the server would reject.
const BODY_MAX_LEN = 4096;
const DEEPLINK_MAX_LEN = 256;
const LANGUAGE_MAX_LEN = 16;
const DEEPLINK_ERROR = "Ссылка должна начинаться с https:// или tg://";

function parseOptionalNonNegativeInt(raw: string): number | undefined {
  const value = raw.trim();
  if (!value) return undefined;
  if (!/^\d+$/.test(value)) return undefined;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : undefined;
}

function nonNegativeIntError(raw: string): string | null {
  return raw.trim() && parseOptionalNonNegativeInt(raw) === undefined
    ? "Введите целое число 0 или больше"
    : null;
}

function hasRawUrlWhitespaceOrControl(value: string): boolean {
  for (const ch of value) {
    const code = ch.charCodeAt(0);
    if (code <= 0x20 || code === 0x7f) return true;
  }
  return false;
}

function validateDeeplink(raw: string): string | null {
  const v = raw.trim();
  if (!v) return null;
  if (v.length > DEEPLINK_MAX_LEN) {
    return `Ссылка слишком длинная (≤${DEEPLINK_MAX_LEN})`;
  }
  if (hasRawUrlWhitespaceOrControl(v)) {
    return DEEPLINK_ERROR;
  }
  let parsed: URL;
  try {
    parsed = new URL(v);
  } catch {
    return DEEPLINK_ERROR;
  }
  const low = v.toLowerCase();
  if (parsed.protocol === "https:") {
    if (!low.startsWith("https://") || v.charAt("https://".length) === "/") {
      return DEEPLINK_ERROR;
    }
    if (!parsed.hostname || parsed.username || parsed.password) {
      return DEEPLINK_ERROR;
    }
    return null;
  }
  if (parsed.protocol === "tg:") {
    if (!low.startsWith("tg://") || v.charAt("tg://".length) === "/") {
      return DEEPLINK_ERROR;
    }
    if (!parsed.hostname) {
      return DEEPLINK_ERROR;
    }
    return null;
  }
  return DEEPLINK_ERROR;
}

function validateLanguage(raw: string): string | null {
  const v = raw.trim();
  if (!v) return null;
  if (v.length > LANGUAGE_MAX_LEN) {
    return `Языковой код слишком длинный (≤${LANGUAGE_MAX_LEN})`;
  }
  return /^[a-z0-9-]+$/i.test(v) ? null : "Используйте латиницу, цифры и дефис";
}

function Composer({ onClose }: { onClose: () => void }) {
  const [body, setBody] = useState("");
  const [title, setTitle] = useState("");
  const [deeplink, setDeeplink] = useState("");
  const [audienceRole, setAudienceRole] = useState<"" | "admin" | "arbiter" | "vip" | "regular">(
    "",
  );
  const [activeDays, setActiveDays] = useState("");
  const [minDeals, setMinDeals] = useState("");
  const [language, setLanguage] = useState("");
  const [inApp, setInApp] = useState(true);
  const [dm, setDm] = useState(false);
  const [previewCount, setPreviewCount] = useState<string | null>(null);
  const preview = useAdminBroadcastPreview();
  const create = useAdminCreateBroadcast();
  const toast = useToast();

  const deeplinkError = validateDeeplink(deeplink);
  const languageError = validateLanguage(language);
  const activeDaysError = nonNegativeIntError(activeDays);
  const minDealsError = nonNegativeIntError(minDeals);
  const dispatchError = !inApp && !dm ? "Выберите хотя бы один канал доставки" : null;
  const bodyOverLimit = body.length > BODY_MAX_LEN;
  const submitBlocked =
    !body.trim() ||
    bodyOverLimit ||
    deeplinkError !== null ||
    languageError !== null ||
    dispatchError !== null ||
    activeDaysError !== null ||
    minDealsError !== null;

  const buildBody = (): AdminBroadcastCreateBody => ({
    title: title.trim() || undefined,
    body: body.trim(),
    deeplink: deeplink.trim() || undefined,
    audience_role: audienceRole || undefined,
    audience_active_days: parseOptionalNonNegativeInt(activeDays),
    audience_min_deals: parseOptionalNonNegativeInt(minDeals),
    audience_language: language.trim() ? language.trim().toLowerCase() : undefined,
    dispatch_inapp: inApp,
    dispatch_dm: dm,
  });

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-text-muted mb-1">Заголовок (необязательно)</label>
        <Input value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div>
        <div className="flex items-end justify-between mb-1">
          <label className="block text-xs text-text-muted">Текст</label>
          <span
            className={`text-[11px] tabular-nums ${
              bodyOverLimit ? "text-danger" : "text-text-muted"
            }`}
            aria-live="polite"
          >
            {body.length}/{BODY_MAX_LEN}
          </span>
        </div>
        <Textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={4}
          placeholder="Что отправляем..."
          error={bodyOverLimit ? `Текст слишком длинный (≤${BODY_MAX_LEN})` : undefined}
        />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Глубокая ссылка (deeplink)</label>
        <Input
          value={deeplink}
          onChange={(e) => setDeeplink(e.target.value)}
          placeholder="https://t.me/your_bot/app?... или tg://resolve?domain=..."
          error={deeplinkError ?? undefined}
        />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Аудитория</label>
        <div className="flex flex-wrap gap-1.5">
          {ROLES.map((r) => (
            <button
              key={r.value || "any"}
              type="button"
              onClick={() => setAudienceRole(r.value)}
              className={`rounded-button px-3 py-1.5 text-sm transition ${
                r.value === audienceRole
                  ? "bg-accent text-accent-fg font-medium"
                  : "bg-panel-2 text-text-muted"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="block text-xs text-text-muted mb-1">
            Активен последние (дни)
          </label>
          <Input
            aria-label="active days"
            inputMode="numeric"
            value={activeDays}
            onChange={(e) => setActiveDays(e.target.value)}
            error={activeDaysError ?? undefined}
          />
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1">Мин. сделок</label>
          <Input
            aria-label="minimum deals"
            inputMode="numeric"
            value={minDeals}
            onChange={(e) => setMinDeals(e.target.value)}
            error={minDealsError ?? undefined}
          />
        </div>
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">
          Язык клиента (например, ru / en / pt-br)
        </label>
        <Input
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          placeholder="ru"
          maxLength={LANGUAGE_MAX_LEN}
          error={languageError ?? undefined}
        />
      </div>
      <div className="bg-panel-2 rounded-button p-2 space-y-2">
        <Switch checked={inApp} onChange={setInApp} label="In-app уведомление" />
        <Switch checked={dm} onChange={setDm} label="Telegram DM (от бота)" />
        {dispatchError && <div className="text-xs text-danger">{dispatchError}</div>}
      </div>
      {previewCount !== null && (
        <div
          className="text-sm text-center bg-accent/10 text-accent rounded-button py-2"
        >
          Будет отправлено: {previewCount}
        </div>
      )}
      {/*
        Sticky-footer for the primary actions. The Composer form has
        grown long enough that the «Отправить» button used to fall
        below the fold on TMA, leaving the operator with no visible
        affordance and the impression that the page was broken.
        ``sticky bottom-0`` keeps the action row anchored to the
        Sheet body's viewport while the form above stays scrollable.
        The ``-mx-4`` neutralises the scroll container's ``px-4`` so
        the border/background run edge-to-edge.
      */}
      <div className="sticky bottom-0 -mx-4 mt-2 border-t border-border bg-panel/95 backdrop-blur px-4 pt-3 pb-[calc(env(safe-area-inset-bottom,0px)+12px)]">
        <div className="flex gap-2">
          <Button
            type="button"
            variant="ghost"
            className="flex-1"
            disabled={submitBlocked || preview.isPending}
            onClick={async () => {
              try {
                const res = await preview.mutateAsync(buildBody());
                setPreviewCount(formatAdminCount(res.total_recipients));
              } catch (e) {
                toast.show({
                  kind: "error",
                  title: "Ошибка",
                  body: (e as Error).message,
                });
              }
            }}
          >
            Предпросмотр
          </Button>
          <Button
            type="button"
            disabled={submitBlocked || create.isPending}
            className="flex-1"
            onClick={async () => {
              try {
                const res = await create.mutateAsync(buildBody());
                toast.show({
                  kind: "success",
                  title: "Отправлено",
                  body: `${formatAdminCount(res.total_recipients)} получателей`,
                });
                onClose();
              } catch (e) {
                toast.show({
                  kind: "error",
                  title: "Ошибка",
                  body: (e as Error).message,
                });
              }
            }}
          >
            <Send size={14} className="mr-1" /> Отправить
          </Button>
        </div>
      </div>
    </div>
  );
}
