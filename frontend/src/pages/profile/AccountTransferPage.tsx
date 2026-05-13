import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRightLeft, RefreshCcw, ShieldAlert } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Header } from "@/components/layout/Header";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ToggleTabs } from "@/components/ui/ToggleTabs";
import { useToast } from "@/components/ui/Toast";
import {
  useAccountTransferStatus,
  useCancelAccountTransfer,
  useConfirmAccountTransfer,
  useStartAccountTransfer,
} from "@/api/hooks";
import { clearPinToken } from "@/lib/pin";
import { haptic } from "@/lib/tg";

type Tab = "send" | "receive";

function relativeMinutes(expiresAt: string | null | undefined): string {
  if (!expiresAt) return "—";
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return "истёк";
  const minutes = Math.ceil(ms / 60_000);
  return `${minutes} мин.`;
}

export default function AccountTransferPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("send");

  const status = useAccountTransferStatus();
  const startMutation = useStartAccountTransfer();
  const cancelMutation = useCancelAccountTransfer();
  const confirmMutation = useConfirmAccountTransfer();

  const [code, setCode] = useState("");

  // Re-render every 15s so the countdown stays roughly fresh without
  // pulling the data again.
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 15_000);
    return () => window.clearInterval(id);
  }, []);

  const onStart = async () => {
    try {
      const res = await startMutation.mutateAsync();
      haptic("success");
      if (res.delivered) {
        toast.show({
          kind: "success",
          title: "Код отправлен в Telegram",
          body: "Откройте чат с ботом — код действует 15 минут.",
        });
      } else {
        toast.show({
          kind: "info",
          title: "Код выпущен",
          body: "Сообщение в боте не доставлено — проверьте, что бот запущен и не заблокирован.",
        });
      }
    } catch (e: unknown) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error)?.message || "Не удалось выпустить код" });
    }
  };

  const onCancel = async () => {
    try {
      await cancelMutation.mutateAsync();
      haptic("success");
      toast.show({ kind: "info", title: "Активный код отменён" });
    } catch (e: unknown) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error)?.message || "Не удалось отменить" });
    }
  };

  const onConfirm = async () => {
    if (!/^\d{6}$/.test(code)) {
      haptic("error");
      toast.show({ kind: "error", title: "Введите 6-значный код" });
      return;
    }
    try {
      await confirmMutation.mutateAsync(code);
      haptic("success");
      // Source account keeps its PIN. Force the gate to re-prompt by
      // clearing the local token, then jump to /profile so the freshly
      // resolved /api/me lookup hits the transferred user record.
      clearPinToken();
      toast.show({
        kind: "success",
        title: "Аккаунт перенесён",
        body: "Введите PIN, чтобы продолжить работу.",
      });
      setCode("");
      window.setTimeout(() => navigate("/profile"), 600);
    } catch (e: unknown) {
      haptic("error");
      toast.show({ kind: "error", title: (e as Error)?.message || "Код не подошёл" });
    }
  };

  const hasActive = !!status.data?.has_active;

  return (
    <Page showBack>
      <Header
        title="Перенос аккаунта"
        subtitle="Привяжите профиль к другому Telegram-аккаунту"
      />

      <div className="px-4 space-y-3">
        <div className="bg-panel border border-border rounded-card p-3 flex items-start gap-3 text-sm">
          <ShieldAlert className="size-5 text-accent shrink-0 mt-0.5" />
          <div className="text-text-muted">
            История, баланс и отзывы остаются на профиле — меняется только
            привязка к Telegram. Перенос работает только на пустой новый
            аккаунт.
          </div>
        </div>

        <ToggleTabs
          value={tab}
          options={[
            { value: "send", label: "Отправить код" },
            { value: "receive", label: "Ввести код" },
          ]}
          onChange={setTab}
          layoutId="account-transfer-tabs"
        />

        {tab === "send" && (
          <div className="bg-panel border border-border rounded-card p-4 space-y-3">
            <div className="text-sm text-text-muted">
              Выпустите одноразовый код на этом аккаунте. Код придёт в
              чат с ботом и действует 15 минут.
            </div>

            {hasActive && (
              <div className="bg-panel-2 rounded-2xl p-3 text-sm">
                <div className="font-semibold">Код уже выпущен</div>
                <div className="text-text-muted mt-0.5">
                  Действует ещё {relativeMinutes(status.data?.expires_at)}.
                  Откройте бота, чтобы увидеть его.
                </div>
              </div>
            )}

            <div className="grid grid-cols-2 gap-2">
              <Button
                fullWidth
                onClick={onStart}
                disabled={startMutation.isPending}
              >
                <RefreshCcw className="size-4" />
                {hasActive ? "Выпустить новый" : "Выпустить код"}
              </Button>
              <Button
                fullWidth
                variant="secondary"
                onClick={onCancel}
                disabled={!hasActive || cancelMutation.isPending}
              >
                Отменить
              </Button>
            </div>
          </div>
        )}

        {tab === "receive" && (
          <div className="bg-panel border border-border rounded-card p-4 space-y-3">
            <div className="text-sm text-text-muted">
              Откройте Garant на новом Telegram-аккаунте, вернитесь сюда
              и введите код. Аккаунт, с которого вы вводите код, должен
              быть пустым (без сделок, услуг и баланса).
            </div>
            <Input
              label="Код из бота"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="123456"
              inputMode="numeric"
              autoComplete="one-time-code"
            />
            <Button
              fullWidth
              onClick={onConfirm}
              disabled={confirmMutation.isPending || code.length !== 6}
            >
              <ArrowRightLeft className="size-4" />
              {confirmMutation.isPending ? "Переношу..." : "Перенести аккаунт"}
            </Button>
          </div>
        )}
      </div>
    </Page>
  );
}
