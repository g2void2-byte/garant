import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldCheck, ShieldOff, KeyRound, Copy } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { AdminHeader } from "@/components/layout/AdminHeader";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { useToast } from "@/components/ui/Toast";
import {
  useAdmin2faDisable,
  useAdmin2faEnable,
  useAdmin2faSetup,
  useAdmin2faStatus,
} from "@/api/admin/hooks";
import { useAdminRedirect } from "@/hooks/useAdminRedirect";

/**
 * `/admin/2fa` — TOTP enrolment for admins.
 *
 * Flow: tap "Включить 2FA" → server returns a base32 secret + an
 * ``otpauth://`` URL. The admin scans the URL with Google Authenticator
 * / 1Password / Aegis, types in the 6-digit code; backend verifies
 * before persisting ``users.totp_secret``.
 *
 * 2FA protects dangerous admin mutations (for example manual wallet
 * adjustments) — `require_totp` checks ``X-Totp-Code``.
 */
export default function AdminTwoFactorPage() {
  const navigate = useNavigate();
  const status = useAdmin2faStatus();
  const setup = useAdmin2faSetup();
  const enable = useAdmin2faEnable();
  const disable = useAdmin2faDisable();
  const toast = useToast();
  const [secret, setSecret] = useState<string | null>(null);
  const [otpauth, setOtpauth] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [disableCode, setDisableCode] = useState("");

  const __guard = useAdminRedirect();
  if (!__guard.shouldRender) return null;

  const enabled = status.data?.enabled ?? false;

  return (
    <Page showBack onBack={() => navigate(-1)}>
      <AdminHeader
        title="2FA"
        subtitle={enabled ? "Включена" : "Не настроена"}
      />
      <div className="px-4 space-y-3 pb-24">
        <div
          className={`rounded-card p-4 flex items-center gap-3 ${
            enabled
              ? "bg-success/10 border border-success/30"
              : "bg-warning/10 border border-warning/30"
          }`}
        >
          {enabled ? (
            <ShieldCheck className="text-success" />
          ) : (
            <ShieldOff className="text-warning" />
          )}
          <div className="flex-1">
            <div className="font-medium">
              {enabled
                ? "2FA активна для вашего аккаунта"
                : "2FA не настроена"}
            </div>
            <div className="text-xs text-text-muted">
              Требуется для опасных админ-действий: ручных корректировок
              баланса, решений по выводам и системных операций.
            </div>
          </div>
        </div>

        {!enabled && !secret && (
          <Button
            type="button"
            onClick={async () => {
              try {
                const res = await setup.mutateAsync();
                setSecret(res.secret);
                setOtpauth(res.otpauth_url);
              } catch (e) {
                toast.show({
                  kind: "error",
                  title: "Ошибка",
                  body: (e as Error).message,
                });
              }
            }}
            className="w-full"
          >
            <KeyRound size={14} className="mr-1" /> Включить 2FA
          </Button>
        )}

        {!enabled && secret && (
          <div
            className="bg-panel rounded-card p-3 space-y-3"
          >
            <div>
              <div className="text-xs text-text-muted mb-1">
                Секрет (вставьте в Google Authenticator / 1Password / Aegis):
              </div>
              <div className="bg-panel-2 rounded-button p-2 flex items-center gap-2">
                <code className="font-mono text-sm flex-1 break-all">{secret}</code>
                <button
                  type="button"
                  onClick={() => {
                    navigator.clipboard.writeText(secret);
                    toast.show({ kind: "info", title: "Скопировано" });
                  }}
                  className="text-text-muted active:scale-90"
                >
                  <Copy size={14} />
                </button>
              </div>
            </div>
            {otpauth && (
              <div className="text-xs text-text-muted break-all">
                otpauth: <code className="text-text">{otpauth}</code>
              </div>
            )}
            <div>
              <label className="block text-xs text-text-muted mb-1">
                Введите текущий код для подтверждения
              </label>
              <Input
                inputMode="numeric"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                pattern="[0-9]{6}"
                maxLength={6}
                placeholder="123 456"
              />
            </div>
            <Button
              type="button"
              disabled={enable.isPending || code.length < 6}
              onClick={async () => {
                try {
                  await enable.mutateAsync({ secret, code });
                  toast.show({ kind: "success", title: "2FA включена" });
                  setSecret(null);
                  setOtpauth(null);
                  setCode("");
                } catch (e) {
                  toast.show({
                    kind: "error",
                    title: "Ошибка",
                    body: (e as Error).message,
                  });
                }
              }}
              className="w-full"
            >
              Подтвердить
            </Button>
          </div>
        )}

        {enabled && (
          <div className="bg-panel rounded-card p-3 space-y-2">
            <div className="text-xs text-text-muted">
              Чтобы отключить, введите текущий код TOTP:
            </div>
            <Input
              inputMode="numeric"
              value={disableCode}
              onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              pattern="[0-9]{6}"
              maxLength={6}
              placeholder="123 456"
            />
            <Button
              type="button"
              variant="danger"
              disabled={disable.isPending || disableCode.length < 6}
              onClick={async () => {
                try {
                  await disable.mutateAsync({ code: disableCode });
                  toast.show({ kind: "info", title: "2FA отключена" });
                  setDisableCode("");
                } catch (e) {
                  toast.show({
                    kind: "error",
                    title: "Ошибка",
                    body: (e as Error).message,
                  });
                }
              }}
              className="w-full"
            >
              Отключить
            </Button>
          </div>
        )}
      </div>
    </Page>
  );
}
