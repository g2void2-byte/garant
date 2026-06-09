import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  TOTP_NOT_CONFIGURED_EVENT,
  TOTP_REQUIRED_EVENT,
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
 * caches it in localStorage. The original mutation is not replayed
 * here: replaying via raw fetch bypasses React Query callbacks,
 * invalidation and typed error handling, so the operator repeats the
 * action through the same button after the session is established.
 *
 * Mounted once at the App root so any admin route can trigger it.
 * No-ops when no event is in flight.
 */

interface Admin2faSessionOut {
  token: string;
  expires_at: string;
}

export function TotpGate() {
  const toast = useToast();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const onRequired = () => {
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
    if (!/^\d{6}$/.test(trimmed)) {
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
        body: "Код принят. Повторите действие, сессия действует 24 часа.",
      });
      setOpen(false);
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
          pattern="[0-9]{6}"
          maxLength={6}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
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
