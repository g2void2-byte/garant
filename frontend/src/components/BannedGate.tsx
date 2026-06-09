import { useEffect, useState } from "react";
import { ShieldOff, MessageSquareWarning } from "lucide-react";
import { LOCKOUT_EVENT, type LockoutDetail } from "@/api/client";
import { openTelegramLink } from "@/lib/tg";
import { buildTelegramUserUrl } from "@/lib/telegramLinks";

/**
 * Item 24 — global lockout gate.
 *
 * Wraps the whole app shell. When any API call returns the structured
 * 403 ``{code: "banned" | "frozen", ...}`` payload, ``client.ts``
 * dispatches a ``garant:lockout`` window event with the detail; this
 * gate latches into that state and renders a dedicated full-screen
 * ban / freeze page instead of the children — so the user can't keep
 * navigating the (now-broken) app and getting silent toasts.
 *
 * The screen exposes a "Связаться с админом" CTA that opens the
 * Telegram chat of the admin returned in ``admin_username``. The
 * button is hidden if the backend didn't populate the field (which
 * shouldn't happen in production but keeps the gate robust against
 * a deployment with no admins onboarded).
 */
export function BannedGate({ children }: { children: React.ReactNode }) {
  const [lockout, setLockout] = useState<LockoutDetail | null>(null);

  useEffect(() => {
    function onLockout(e: Event) {
      const detail = (e as CustomEvent<LockoutDetail>).detail;
      if (!detail) return;
      setLockout(detail);
    }
    window.addEventListener(LOCKOUT_EVENT, onLockout);
    return () => window.removeEventListener(LOCKOUT_EVENT, onLockout);
  }, []);

  if (!lockout) return <>{children}</>;

  const isBanned = lockout.code === "banned";
  const title = isBanned ? "Аккаунт заблокирован" : "Аккаунт заморожен";
  const subtitle = isBanned
    ? "Доступ к сервису ограничен администратором."
    : "Доступ временно ограничен администратором.";

  function contactAdmin() {
    if (!lockout?.admin_username) return;
    const reason = lockout.reason ? ` (${lockout.reason})` : "";
    const text = `Здравствуйте! Мой аккаунт ${isBanned ? "заблокирован" : "заморожен"}. Прошу уточнить причину${reason} и возможность разбана.`;
    const url = buildTelegramUserUrl(lockout.admin_username, { text });
    if (url) openTelegramLink(url);
  }

  return (
    <div className="min-h-full grid place-items-center bg-bg px-4 py-10">
      <div
        role="alert"
        aria-live="assertive"
        className="w-full max-w-sm rounded-card border border-danger/50 bg-panel p-6 text-center space-y-4"
      >
        <div className="mx-auto size-14 rounded-full bg-danger/15 grid place-items-center">
          <ShieldOff className="size-7 text-danger" />
        </div>
        <div>
          <div className="text-lg font-semibold text-text">{title}</div>
          <div className="mt-1 text-sm text-text-muted">{subtitle}</div>
        </div>
        {lockout.reason && (
          <div className="rounded-card border border-border bg-panel-2 px-3 py-2 text-left text-[13px] text-text">
            <div className="text-[11px] text-text-muted mb-0.5">Причина</div>
            <div className="whitespace-pre-wrap break-words">{lockout.reason}</div>
          </div>
        )}
        {lockout.admin_username ? (
          <button
            type="button"
            onClick={contactAdmin}
            className="w-full inline-flex items-center justify-center gap-2 rounded-button bg-accent text-bg px-4 py-2 text-sm font-semibold active:scale-[0.98] transition"
          >
            <MessageSquareWarning className="size-4" />
            Написать админу
          </button>
        ) : (
          <div className="text-[12px] text-text-muted">
            Свяжитесь с поддержкой через Telegram-бот.
          </div>
        )}
      </div>
    </div>
  );
}
