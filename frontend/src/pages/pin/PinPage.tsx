import { useEffect, useState } from "react";
import {
  useCheckPin,
  useConfirmPinReset,
  useRequestPinReset,
  useSetupPin,
} from "@/api/hooks";
import type { PinStatusDto, PinTokenDto } from "@/api/types";
import { Button } from "@/components/ui/Button";
import { PinPad } from "@/components/ui/PinPad";
import { useToast } from "@/components/ui/Toast";
import { setPinToken } from "@/lib/pin";
import { haptic } from "@/lib/tg";

type Mode = "check" | "setup_first" | "setup_confirm" | "reset_code" | "reset_new" | "reset_new_confirm";

interface PinPageProps {
  status: PinStatusDto;
  onUnlocked: () => void;
}

function formatLock(locked: string | null): string | null {
  if (!locked) return null;
  const ms = new Date(locked).getTime() - Date.now();
  if (ms <= 0) return null;
  const minutes = Math.ceil(ms / 60_000);
  return minutes >= 60 ? `${Math.ceil(minutes / 60)} ч` : `${minutes} мин`;
}

export default function PinPage({ status, onUnlocked }: PinPageProps) {
  const toast = useToast();
  const [pin, setPin] = useState("");
  const [memo, setMemo] = useState("");
  const [resetCode, setResetCode] = useState("");
  const [mode, setMode] = useState<Mode>(() => (status.has_pin ? "check" : "setup_first"));
  const [lockMessage, setLockMessage] = useState<string | null>(formatLock(status.locked_until));

  const setup = useSetupPin();
  const check = useCheckPin();
  const requestReset = useRequestPinReset();
  const confirmReset = useConfirmPinReset();

  // V5-F-7: keep memo/pin in sync with mode flips.
  useEffect(() => {
    if (mode === "setup_first" || mode === "reset_new") {
      setMemo("");
    }
    setPin("");
  }, [mode]);

  // V5-F-7: mount-time wipe (KeepAlive safety).
  useEffect(() => {
    setMemo("");
    setPin("");
    setResetCode("");
  }, []);

  useEffect(() => {
    if (!status.locked_until) return setLockMessage(null);
    setLockMessage(formatLock(status.locked_until));
    const id = setInterval(() => {
      const next = formatLock(status.locked_until);
      setLockMessage(next);
      if (!next) clearInterval(id);
    }, 30_000);
    return () => clearInterval(id);
  }, [status.locked_until]);

  function applyToken(t: PinTokenDto) {
    setPinToken(t.token, t.expires_at);
    haptic("success");
    onUnlocked();
  }

  async function handleComplete(full: string) {
    if (mode === "check") {
      try {
        const t = await check.mutateAsync(full);
        applyToken(t);
      } catch (e: any) {
        haptic("error");
        toast.show({ kind: "error", title: e?.message || "Неверный PIN" });
        setPin("");
      }
      return;
    }
    if (mode === "setup_first") {
      setMemo(full);
      setPin("");
      setMode("setup_confirm");
      return;
    }
    if (mode === "setup_confirm") {
      if (full !== memo) {
        haptic("error");
        toast.show({ kind: "error", title: "PIN не совпадает. Попробуйте ещё раз." });
        setPin("");
        setMode("setup_first");
        setMemo("");
        return;
      }
      try {
        const t = await setup.mutateAsync(memo);
        applyToken(t);
      } catch (e: any) {
        toast.show({ kind: "error", title: e?.message || "Не удалось установить PIN" });
        setPin("");
        setMode("setup_first");
        setMemo("");
      }
      return;
    }
    if (mode === "reset_new") {
      setMemo(full);
      setPin("");
      setMode("reset_new_confirm");
      return;
    }
    if (mode === "reset_new_confirm") {
      if (full !== memo) {
        toast.show({ kind: "error", title: "PIN не совпадает" });
        setPin("");
        setMode("reset_new");
        setMemo("");
        return;
      }
      try {
        const t = await confirmReset.mutateAsync({ code: resetCode, new_pin: memo });
        applyToken(t);
      } catch (e: any) {
        toast.show({ kind: "error", title: e?.message || "Не удалось сбросить PIN" });
        setPin("");
        setMode("reset_code");
        setMemo("");
      }
    }
  }

  async function startReset() {
    try {
      const r = await requestReset.mutateAsync();
      if (r.delivered) {
        toast.show({ kind: "info", title: "Код отправлен в Telegram" });
      } else {
        toast.show({
          kind: "error",
          title: "Бот не смог отправить вам сообщение",
          body: "Напишите /start боту и попробуйте снова.",
        });
      }
      setResetCode("");
      setMode("reset_code");
    } catch (e: any) {
      toast.show({ kind: "error", title: e?.message || "Не удалось запросить сброс" });
    }
  }

  const locked = !!lockMessage;
  const titles: Record<Mode, { title: string; subtitle: string }> = {
    check: { title: "Введите PIN", subtitle: locked ? `Заблокировано. Попробуйте через ${lockMessage}.` : "Чтобы продолжить, введите ваш 4-значный PIN" },
    setup_first: { title: "Создайте PIN", subtitle: "Придумайте 4 цифры для входа" },
    setup_confirm: { title: "Подтвердите PIN", subtitle: "Введите PIN ещё раз" },
    reset_code: { title: "Сброс PIN", subtitle: "Введите 6-значный код из Telegram" },
    reset_new: { title: "Новый PIN", subtitle: "Придумайте новые 4 цифры" },
    reset_new_confirm: { title: "Подтвердите новый PIN", subtitle: "Введите его ещё раз" },
  };
  const heading = titles[mode];
  const showPad = mode !== "reset_code";

  return (
    <div className="min-h-full flex flex-col items-center justify-center px-6 py-10 bg-bg text-text">
      <div
        key={mode}
        className="text-center mb-10 animate-fadein"
      >
        <h1 className="text-2xl font-semibold">{heading.title}</h1>
        <p className="text-text-muted mt-2 text-sm max-w-xs">{heading.subtitle}</p>
      </div>

      {showPad ? (
        <PinPad
          value={pin}
          onChange={setPin}
          onComplete={handleComplete}
          disabled={locked || check.isPending || setup.isPending || confirmReset.isPending}
        />
      ) : (
        <div className="w-full max-w-xs flex flex-col items-center gap-4">
          <input
            value={resetCode}
            onChange={(e) => setResetCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            autoFocus
            placeholder="000000"
            className="w-full text-center text-2xl tracking-[0.5em] bg-panel border border-border rounded-2xl py-3 outline-none focus:border-accent"
          />
          <Button
            variant="primary"
            fullWidth
            disabled={resetCode.length !== 6}
            onClick={() => setMode("reset_new")}
          >
            Продолжить
          </Button>
          <button
            type="button"
            className="text-text-muted text-sm underline"
            onClick={() => {
              setMode(status.has_pin ? "check" : "setup_first");
              setPin("");
              setMemo("");
              setResetCode("");
            }}
          >
            Отмена
          </button>
        </div>
      )}

      {mode === "check" && (
        <div className="mt-10 flex flex-col items-center gap-2 text-sm">
          {locked ? (
            <span className="text-danger">Слишком много попыток. Ждите {lockMessage}.</span>
          ) : (
            <span className="text-text-muted">Осталось попыток: {status.attempts_left}</span>
          )}
          <button
            type="button"
            onClick={startReset}
            className="text-accent underline"
            disabled={requestReset.isPending}
          >
            Забыли PIN?
          </button>
        </div>
      )}
    </div>
  );
}
