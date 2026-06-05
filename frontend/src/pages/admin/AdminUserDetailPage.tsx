import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Ban,
  CheckCircle2,
  Crown,
  Gavel,
  KeyRound,
  LogOut,
  Minus,
  Plus,
  Snowflake,
  Star,
  Trash2,
  Wallet,
  ShieldCheck,
} from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { BadgePrefix } from "@/components/ui/BadgePrefix";
import { Avatar } from "@/components/ui/Avatar";
import { useToast } from "@/components/ui/Toast";
import {
  useAdminAdjustBalance,
  useAdminBanUser,
  useAdminCurrencies,
  useAdminFreezeUser,
  useAdminInvalidateSessions,
  useAdminResetPin,
  useAdminSetRating,
  useAdminSetRole,
  useAdminSetStats,
  useAdminSetTrustDeposit,
  useAdminUnbanUser,
  useAdminUnfreezeUser,
  useAdminUser,
  useAdminUserWallet,
} from "@/api/admin/hooks";
import { useMe } from "@/api/hooks";
import type { AdminUserDetailDto } from "@/api/types";
import { formatDateTime, parseDecimal } from "@/lib/format";
import {
  parseNonNegativeDecimalInput,
  parseNonNegativeIntInput,
  parsePositiveDecimalInput,
} from "@/lib/formNumbers";
import { haptic } from "@/lib/tg";
import { ServicesSection, ReviewsSection, CommentsSection } from "./UserContentSections";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";
import { parsePositiveIntRouteParam } from "@/lib/routeParams";
import { formatAdminCount, formatAdminId, formatAdminRating, formatAdminUsd, formatAdminUsername } from "./format";

/**
 * Continental admin user detail screen.
 *
 * Sections (top → bottom):
 *   1. Identity card (avatar, names, prefix, tg_user_id, last_ip, sessions)
 *   2. Moderation actions (ban/unban, freeze/unfreeze, reset-PIN, invalidate sessions)
 *   3. Roles (Admin / Arbiter / VIP toggles, saved atomically)
 *   4. Rating override
 *   5. Stats editor (deals_total / good / bad / ...)
 *
 * Each section is its own subcomponent — they all share the same
 * mutation pattern (mutate → toast → invalidate via hook).
 */

function normalizeDecimalInput(raw: string): string {
  return raw.trim().replace(",", ".");
}

function parseAdminNonNegativeDecimal(raw: string): number | null {
  return parseNonNegativeDecimalInput(normalizeDecimalInput(raw));
}

function parseAdminPositiveDecimal(raw: string): number | null {
  return parsePositiveDecimalInput(normalizeDecimalInput(raw));
}

function parseRatingOverride(raw: string): number | null {
  const parsed = parseAdminNonNegativeDecimal(raw);
  return parsed !== null && parsed <= 5 ? parsed : null;
}

export default function AdminUserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const userId = parsePositiveIntRouteParam(id);
  const navigate = useNavigate();
  const { data: me } = useMe();
  const { data: user, isLoading } = useAdminUser(userId);

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  if (!userId) {
    return (
      <Page showBack onBack={() => navigate(-1)}>
        <AdminHeader title="Пользователь" />
        <p className="px-4 text-sm text-text-muted">Неверный ID.</p>
      </Page>
    );
  }

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader title="Пользователь" />
      {isLoading || !user ? (
        <div className="px-4 space-y-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-40" />
          <Skeleton className="h-32" />
        </div>
      ) : (
        <div className="px-4 space-y-4 pb-8">
          <IdentityCard user={user} />
          <ModerationSection user={user} isSelf={user.id === me?.id} />
          <RolesSection user={user} isSelf={user.id === me?.id} />
          <RatingSection user={user} />
          <StatsSection user={user} />
          <TrustDepositSection user={user} />
          <BalanceSection user={user} />
          <ServicesSection userId={user.id} />
          <ReviewsSection userId={user.id} />
          <CommentsSection userId={user.id} />
        </div>
      )}
    </Page>
  );
}

// ── Identity ───────────────────────────────────────────────────────────

function IdentityCard({ user }: { user: AdminUserDetailDto }) {
  return (
    <section className="bg-panel rounded-card p-4">
      <div className="flex items-start gap-3">
        <Avatar name={user.display_name} src={user.photo_url} size={64} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <h2 className="font-semibold truncate">{user.display_name}</h2>
            <BadgePrefix prefix={pickPrefix(user)} />
          </div>
          <div className="text-xs text-text-muted">{formatAdminUsername(user.username)}</div>
          <div className="text-xs text-text-muted">tg_id: {formatAdminId(user.tg_user_id)}</div>
        </div>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <Detail label="Создан" value={shortDate(user.created_at)} />
        <Detail label="Последний вход" value={user.last_login_at ? shortDate(user.last_login_at) : "—"} />
        <Detail label="IP" value={user.last_ip ?? "—"} mono />
        <Detail label="Входов всего" value={formatAdminCount(user.login_count)} />
        <Detail
          label="Трастовый депозит"
          value={formatAdminUsd(user.trust_deposit_balance)}
        />
        <Detail label="Рейтинг" value={formatAdminRating(user.rating_effective)} />
        <Detail label="PIN" value={user.has_pin ? "Установлен" : "Нет"} />
      </dl>

      {(user.is_banned || user.is_frozen) && (
        <div className="mt-3 space-y-1 text-xs">
          {user.is_banned && (
            <p className="text-danger">Бан · {user.ban_reason ?? "без причины"}</p>
          )}
          {user.is_frozen && (
            <p className="text-warning">Заморожен · {user.freeze_reason ?? "без причины"}</p>
          )}
        </div>
      )}
    </section>
  );
}

function pickPrefix(user: AdminUserDetailDto) {
  if (user.is_admin) return "admin";
  if (user.is_arbiter) return "arbiter";
  if (user.is_vip) return "vip";
  return null;
}

function Detail({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-text-muted">{label}</dt>
      <dd className={mono ? "font-mono" : ""}>{value}</dd>
    </div>
  );
}

function shortDate(iso: string) {
  return formatDateTime(iso, { dateStyle: "short", timeStyle: "short" });
}

// ── Moderation actions ────────────────────────────────────────────────

function ModerationSection({ user, isSelf }: { user: AdminUserDetailDto; isSelf: boolean }) {
  const toast = useToast();
  const ban = useAdminBanUser();
  const unban = useAdminUnbanUser();
  const freeze = useAdminFreezeUser();
  const unfreeze = useAdminUnfreezeUser();
  const resetPin = useAdminResetPin();
  const invalidate = useAdminInvalidateSessions();

  const [banReason, setBanReason] = useState("");
  const [freezeReason, setFreezeReason] = useState("");

  const run = async <T,>(
    label: string,
    mutateAsync: (args: { userId: number; body?: Record<string, unknown> }) => Promise<T>,
    body?: Record<string, unknown>,
  ) => {
    try {
      await mutateAsync({ userId: user.id, body });
      haptic("success");
      toast.show({ kind: "success", title: label });
    } catch (e) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error).message || "Не удалось" });
    }
  };

  return (
    <section className="bg-panel rounded-card p-4 space-y-4">
      <h3 className="font-semibold text-sm">Модерация</h3>

      <div className="space-y-2">
        <Input
          placeholder="Причина бана (опционально)"
          value={banReason}
          onChange={(e) => setBanReason(e.target.value)}
        />
        <div className="flex gap-2">
          <Button
            variant="danger"
            size="sm"
            fullWidth
            disabled={isSelf || ban.isPending}
            onClick={() => run("Забанен", ban.mutateAsync, { reason: banReason || null })}
          >
            <Ban size={16} /> Забанить
          </Button>
          <Button
            variant="secondary"
            size="sm"
            fullWidth
            disabled={!user.is_banned || unban.isPending}
            onClick={() => run("Разбанен", unban.mutateAsync)}
          >
            <CheckCircle2 size={16} /> Снять бан
          </Button>
        </div>
      </div>

      <div className="space-y-2">
        <Input
          placeholder="Причина заморозки (опционально)"
          value={freezeReason}
          onChange={(e) => setFreezeReason(e.target.value)}
        />
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            fullWidth
            disabled={isSelf || freeze.isPending}
            onClick={() => run("Заморожен", freeze.mutateAsync, { reason: freezeReason || null })}
          >
            <Snowflake size={16} /> Заморозить
          </Button>
          <Button
            variant="secondary"
            size="sm"
            fullWidth
            disabled={!user.is_frozen || unfreeze.isPending}
            onClick={() => run("Разморожен", unfreeze.mutateAsync)}
          >
            <CheckCircle2 size={16} /> Разморозить
          </Button>
        </div>
      </div>

      <div className="flex gap-2">
        <Button
          variant="secondary"
          size="sm"
          fullWidth
          disabled={!user.has_pin || resetPin.isPending}
          onClick={() => run("PIN сброшен", resetPin.mutateAsync)}
        >
          <KeyRound size={16} /> Сбросить PIN
        </Button>
        <Button
          variant="secondary"
          size="sm"
          fullWidth
          disabled={isSelf || invalidate.isPending}
          onClick={() => run("Сессии сброшены", invalidate.mutateAsync)}
        >
          <LogOut size={16} /> Разлогинить
        </Button>
      </div>
    </section>
  );
}

// ── Roles ─────────────────────────────────────────────────────────────

function RolesSection({ user, isSelf }: { user: AdminUserDetailDto; isSelf: boolean }) {
  const toast = useToast();
  const setRole = useAdminSetRole();
  const [isAdmin, setIsAdmin] = useState(user.is_admin);
  const [isArbiter, setIsArbiter] = useState(user.is_arbiter);
  const [isVip, setIsVip] = useState(user.is_vip);

  const dirty =
    isAdmin !== user.is_admin || isArbiter !== user.is_arbiter || isVip !== user.is_vip;

  const apply = async () => {
    try {
      await setRole.mutateAsync({
        userId: user.id,
        body: { is_admin: isAdmin, is_arbiter: isArbiter, is_vip: isVip },
      });
      haptic("success");
      toast.show({ kind: "success", title: "Роли обновлены" });
    } catch (e) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error).message || "Не удалось" });
    }
  };

  return (
    <section className="bg-panel rounded-card p-4 space-y-3">
      <h3 className="font-semibold text-sm">Роли</h3>
      <RoleToggle
        icon={<ShieldCheck size={18} />}
        label="Админ"
        checked={isAdmin}
        disabled={isSelf}
        onChange={setIsAdmin}
      />
      <RoleToggle
        icon={<Gavel size={18} />}
        label="Арбитр"
        checked={isArbiter}
        onChange={setIsArbiter}
      />
      <RoleToggle
        icon={<Crown size={18} />}
        label="VIP"
        checked={isVip}
        onChange={setIsVip}
      />
      <Button
        variant="primary"
        size="sm"
        fullWidth
        disabled={!dirty || setRole.isPending}
        onClick={apply}
      >
        Сохранить роли
      </Button>
    </section>
  );
}

function RoleToggle({
  icon,
  label,
  checked,
  disabled,
  onChange,
}: {
  icon: React.ReactNode;
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className={`flex items-center gap-3 ${disabled ? "opacity-50" : ""}`}>
      <span className="text-text-muted">{icon}</span>
      <span className="flex-1 text-sm">{label}</span>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="w-5 h-5 accent-accent"
      />
    </label>
  );
}

// ── Rating ────────────────────────────────────────────────────────────

function RatingSection({ user }: { user: AdminUserDetailDto }) {
  const toast = useToast();
  const setRating = useAdminSetRating();
  const [draft, setDraft] = useState(
    user.rating_manual !== null ? String(user.rating_manual) : "",
  );

  const save = async (clear = false) => {
    const value = clear ? null : parseRatingOverride(draft);
    if (!clear && value === null) {
      toast.show({ kind: "error", title: "Неверное число" });
      return;
    }
    try {
      await setRating.mutateAsync({
        userId: user.id,
        body: { rating: value },
      });
      haptic("success");
      toast.show({
        kind: "success",
        title: clear ? "Сброшено" : "Рейтинг сохранён",
      });
      if (clear) setDraft("");
    } catch (e) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error).message || "Не удалось" });
    }
  };

  return (
    <section className="bg-panel rounded-card p-4 space-y-3">
      <h3 className="font-semibold text-sm flex items-center gap-2">
        <Star size={16} /> Рейтинг (0..5)
      </h3>
      <p className="text-xs text-text-muted">
        Авто-рейтинг: {formatAdminRating(user.rating_auto)} · Сейчас:{" "}
        {formatAdminRating(user.rating_effective)}
        {user.rating_manual !== null && " (override)"}
      </p>
      <Input
        type="number"
        step="0.1"
        min="0"
        max="5"
        placeholder="Например 4.8"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <div className="flex gap-2">
        <Button
          variant="primary"
          size="sm"
          fullWidth
          disabled={setRating.isPending || draft === ""}
          onClick={() => save(false)}
        >
          Сохранить
        </Button>
        <Button
          variant="secondary"
          size="sm"
          fullWidth
          disabled={setRating.isPending || user.rating_manual === null}
          onClick={() => save(true)}
        >
          <Trash2 size={14} /> Сбросить
        </Button>
      </div>
    </section>
  );
}

// ── Stats ─────────────────────────────────────────────────────────────

interface StatsDraft {
  deals_total: string;
  deals_success: string;
  deals_failed: string;
  deals_arbitrage: string;
  deals_sum_override: string;
  good: string;
  bad: string;
}

function StatsSection({ user }: { user: AdminUserDetailDto }) {
  const toast = useToast();
  const setStats = useAdminSetStats();
  const [draft, setDraft] = useState<StatsDraft>({
    deals_total: String(user.deals_total),
    deals_success: String(user.deals_success),
    deals_failed: String(user.deals_failed),
    deals_arbitrage: String(user.deals_arbitrage),
    deals_sum_override: String(user.deals_sum_override ?? 0),
    good: String(user.good),
    bad: String(user.bad),
  });

  const fields: Array<{
    key: keyof StatsDraft;
    label: string;
    type: "int" | "float";
  }> = [
    { key: "deals_total", label: "Сделок всего", type: "int" },
    { key: "deals_success", label: "Успешных", type: "int" },
    { key: "deals_failed", label: "Неуспешных", type: "int" },
    { key: "deals_arbitrage", label: "В арбитраже", type: "int" },
    { key: "deals_sum_override", label: "Сумма сделок ($)", type: "float" },
    { key: "good", label: "Положительных оценок", type: "int" },
    { key: "bad", label: "Отрицательных оценок", type: "int" },
  ];

  const apply = async () => {
    const body: Record<string, number | null> = {};
    for (const f of fields) {
      const raw = draft[f.key];
      if (raw.trim() === "") continue;
      const n = f.type === "int"
        ? parseNonNegativeIntInput(raw)
        : parseAdminNonNegativeDecimal(raw);
      if (n === null) {
        toast.show({ kind: "error", title: `Неверное число: ${f.label}` });
        return;
      }
      body[f.key] = n;
    }
    try {
      await setStats.mutateAsync({ userId: user.id, body });
      haptic("success");
      toast.show({ kind: "success", title: "Статистика сохранена" });
    } catch (e) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error).message || "Не удалось" });
    }
  };

  return (
    <section className="bg-panel rounded-card p-4 space-y-3">
      <h3 className="font-semibold text-sm">Статистика профиля</h3>
      <div className="grid grid-cols-2 gap-2">
        {fields.map((f) => (
          <Input
            key={f.key}
            label={f.label}
            type="number"
            value={draft[f.key]}
            onChange={(e) =>
              setDraft((d) => ({ ...d, [f.key]: e.target.value }))
            }
          />
        ))}
      </div>
      <Button
        variant="primary"
        size="sm"
        fullWidth
        disabled={setStats.isPending}
        onClick={apply}
      >
        Сохранить статистику
      </Button>
    </section>
  );
}

// ── Trust deposit ───────────────────────────────────────────────────

/**
 * Item 12 — the public profile renders ``trust_deposit_balance`` as
 * its ``deposit`` field. This section is the only path to mutate
 * the column from the admin panel.
 */
function TrustDepositSection({ user }: { user: AdminUserDetailDto }) {
  const toast = useToast();
  const setTrust = useAdminSetTrustDeposit();
  const [amount, setAmount] = useState(String(user.trust_deposit_balance));
  const [reason, setReason] = useState("");

  const apply = async () => {
    const n = parseAdminNonNegativeDecimal(amount);
    if (n === null) {
      toast.show({
        kind: "error",
        title: "Введите неотрицательное число",
      });
      return;
    }
    try {
      await setTrust.mutateAsync({
        userId: user.id,
        body: { amount: n, reason: reason.trim() || null },
      });
      haptic("success");
      toast.show({
        kind: "success",
        title: "Трастовый депозит обновлён",
        body: `${user.username ?? formatAdminId(user.tg_user_id)} ← $${n.toFixed(2)}`,
      });
      setReason("");
    } catch (e) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error).message || "Не удалось" });
    }
  };

  return (
    <section className="bg-panel rounded-card p-4 space-y-3">
      <h3 className="font-semibold text-sm flex items-center gap-2">
        <ShieldCheck size={14} />
        Трастовый депозит
      </h3>
      <p className="text-xs text-text-muted">
        Видим пользователю в профиле как «Депозит». Лайфтайм-депозит
        выше — отдельная админская метрика и пользователю не
        показывается.
      </p>
      <Input
        label="Новое значение ($)"
        type="number"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
      />
      <Input
        label="Причина (опционально)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <Button
        variant="primary"
        size="sm"
        fullWidth
        disabled={setTrust.isPending}
        onClick={apply}
      >
        Сохранить трастовый депозит
      </Button>
    </section>
  );
}

// ── Balance ─────────────────────────────────────────────────────────

function BalanceSection({ user }: { user: AdminUserDetailDto }) {
  const { data: balances } = useAdminUserWallet(user.id);
  const { data: currencies } = useAdminCurrencies();
  const adjust = useAdminAdjustBalance(user.id);
  const toast = useToast();
  const fallback =
    balances?.find((b) => parseDecimal(b.total) > 0)?.currency_code ?? "USDT";
  const [currency, setCurrency] = useState<string>(fallback);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const allCurrencies = currencies ?? [];
  const parsedAmount = amount.trim() ? parseAdminPositiveDecimal(amount) : null;
  const amountError = amount.trim() && parsedAmount === null
    ? "Введите положительное число без экспоненты"
    : undefined;

  async function submit(sign: 1 | -1) {
    if (parsedAmount === null) {
      toast.show({
        kind: "error",
        title: "Введите сумму",
        body: "Сумма должна быть положительным числом.",
      });
      return;
    }
    try {
      await adjust.mutateAsync({
        currency_code: currency,
        amount: sign * parsedAmount,
        reason: reason.trim() || undefined,
      });
      toast.show({
        kind: "success",
        title: "Готово",
        body: `${currency} ${sign > 0 ? "+" : "-"}${parsedAmount} применено`,
      });
      setAmount("");
      setReason("");
    } catch (e) {
      toast.show({
        kind: "error",
        title: "Ошибка",
        body: (e as Error).message,
      });
    }
  }

  return (
    <section className="bg-panel rounded-card p-4 space-y-3">
      <h3 className="font-semibold text-sm flex items-center gap-2">
        <Wallet size={14} />
        Баланс пользователя
      </h3>
      {balances && balances.length > 0 ? (
        <div className="space-y-1 text-sm">
          {balances.map((b) => (
            <div
              key={b.currency_code}
              className="flex justify-between bg-panel-2 rounded-button px-3 py-1.5"
            >
              <span className="text-text-muted">{b.currency_code}</span>
              <span className="font-mono">{b.total}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs text-text-muted">Нет балансов</div>
      )}
      <div>
        <label className="block text-xs text-text-muted mb-1">Валюта</label>
        <div className="flex flex-wrap gap-1.5">
          {allCurrencies.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => setCurrency(c.code)}
              className={`rounded-button px-3 py-1.5 text-sm transition ${
                c.code === currency
                  ? "bg-accent text-accent-fg font-medium"
                  : "bg-panel-2 text-text-muted"
              }`}
            >
              {c.code}
            </button>
          ))}
        </div>
      </div>
      <Input
        label="Сумма (положительная)"
        inputMode="decimal"
        value={amount}
        error={amountError}
        onChange={(e) => setAmount(e.target.value)}
        placeholder="25.5"
      />
      <Input
        label="Причина (необязательно)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Возврат / премия / штраф"
      />
      <div className="flex gap-2">
        <Button
          type="button"
          variant="danger"
          className="flex-1"
          disabled={adjust.isPending || parsedAmount === null}
          onClick={() => submit(-1)}
        >
          <Minus size={14} className="mr-1" /> Списать
        </Button>
        <Button
          type="button"
          variant="primary"
          className="flex-1"
          disabled={adjust.isPending || parsedAmount === null}
          onClick={() => submit(1)}
        >
          <Plus size={14} className="mr-1" /> Зачислить
        </Button>
      </div>
    </section>
  );
}
