import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  TOTP_NOT_CONFIGURED_EVENT,
  TOTP_REQUIRED_EVENT,
  type TotpRequiredDetail,
} from "@/api/client";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Sheet } from "@/components/ui/Sheet";
import { useToast } from "@/components/ui/Toast";
import { setTotpSessionToken } from "@/lib/totp";

/**
 * Global 2FA code-entry gate.
 *
 * Listens for the ``garant:totp-required`` event the ky 401
 * interceptor dispatches and renders a bottom sheet asking the
 * operator for one TOTP code. On success the gate mints a 24h
 * ``X-Totp-Session`` JWT via ``POST /api/admin/2fa/session`` (the
 * single source of truth for the 24h "one code per day" rule),
 * caches it in localStorage, and *replays the original failed
 * request* with the new session header attached so the admin
 * action lands without the user having to click the button a
 * second time.
 *
 * Mounted once at the App root so any admin route can trigger it.
 * No-ops when no event is in flight.
 */

interface Admin2faSessionOut {
  token: string;
  expires_at: string;
}

async function replayFailed(detail: TotpRequiredDetail): Promise<void> {
  // We can't go through ``ky`` for the replay because the failed
  // request was already issued *through* ``ky`` — its ``beforeError``
  // hook is what dispatched us here. Using ``ky`` again would
  // double-fire the gate on the off-chance the new session is also
  // rejected. A plain ``fetch`` with the original headers (plus the
  // freshly-cached session token, injected by the ky pre-request
  // hook on subsequent calls anyway) is the simplest one-shot.
  const headers = new Headers(detail.headers);
  headers.delete("x-totp-session");
  const totpToken = window.localStorage.getItem(
    "garant.totp_session_token",
  );
  if (totpToken) headers.set("X-Totp-Session", totpToken);
  try {
    await fetch(detail.url, {
      method: detail.method,
      headers,
      body: detail.body ?? undefined,
      // ``credentials`` mirrors the ``ky`` default — we don't
      // currently emit cross-origin admin calls, but if the
      // operator opens the admin panel under a different sub-domain
      // we keep cookies attached for consistency with the original.
      credentials: "same-origin",
    });
  } catch {
    /* the user can re-trigger manually if the replay itself fails */
  }
}

export function TotpGate() {
  const toast = useToast();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const pending = useRef<TotpRequiredDetail | null>(null);

  useEffect(() => {
    const onRequired = (e: Event) => {
      const ce = e as CustomEvent<TotpRequiredDetail>;
      pending.current = ce.detail ?? null;
      setCode("");
      setOpen(true);
    };
    const onMissing = () => {
      toast.show({
        kind: "error",
        title: "2FA не настроен",
        body: "Включите двухфакторную аутентификацию в админ-панели.",
      });
      navigate("/admin/2fa");
    };
    window.addEventListener(TOTP_REQUIRED_EVENT, onRequired);
    window.addEventListener(TOTP_NOT_CONFIGURED_EVENT, onMissing);
    return () => {
      window.removeEventListener(TOTP_REQUIRED_EVENT, onRequired);
      window.removeEventListener(TOTP_NOT_CONFIGURED_EVENT, onMissing);
    };
  }, [navigate, toast]);

  async function submit() {
    const trimmed = code.trim();
    if (!/^\d{6,8}$/.test(trimmed)) {
      toast.show({
        kind: "error",
        title: "Введите код 2FA",
        body: "6 цифр из приложения-аутентификатора.",
      });
      return;
    }
    setSubmitting(true);
    try {
      const out = await api
        .post("api/admin/2fa/session", { json: { code: trimmed } })
        .json<Admin2faSessionOut>();
      setTotpSessionToken(out.token, out.expires_at);
      toast.show({
        kind: "success",
        title: "2FA подтверждено",
        body: "Код принят. Сессия действует 24 часа.",
      });
      setOpen(false);
      const detail = pending.current;
      pending.current = null;
      if (detail) {
        await replayFailed(detail);
      }
    } catch (err) {
      const message =
        err instanceof Error && err.message ? err.message : "Неверный код 2FA";
      toast.show({ kind: "error", title: "Не удалось войти", body: message });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet open={open} onClose={() => setOpen(false)} title="Введите код 2FA">
      <div className="space-y-3">
        <p className="text-sm text-text-muted">
          Откройте приложение-аутентификатор и введите 6-значный код.
          После подтверждения новый код не понадобится в течение 24
          часов независимо от выполняемого действия.
        </p>
        <Input
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6,8}"
          maxLength={8}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          placeholder="123456"
          aria-label="Код 2FA"
        />
        <div className="flex gap-2 pt-2">
          <Button
            variant="ghost"
            className="flex-1"
            onClick={() => setOpen(false)}
            disabled={submitting}
          >
            Отмена
          </Button>
          <Button
            className="flex-1"
            onClick={submit}
            disabled={submitting || code.length < 6}
          >
            {submitting ? "..." : "Подтвердить"}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}
