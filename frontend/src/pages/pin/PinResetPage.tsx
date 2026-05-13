import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Page } from "@/components/layout/Page";
import { Button } from "@/components/ui/Button";
import { PinPad } from "@/components/ui/PinPad";
import { useToast } from "@/components/ui/Toast";
import {
  useConfirmPinReset,
  useRequestPinReset,
} from "@/api/hooks";
import { setPinToken } from "@/lib/pin";
import { haptic } from "@/lib/tg";

type Step = "request" | "code" | "new" | "confirm";

/**
 * Dedicated «Сменить PIN-код» page reached from `/profile/settings`.
 *
 * Unlike :file:`PinPage` (which interleaves login, setup, and reset on the
 * single splash screen), this page is **only** the password-reset flow:
 * `request → code → new PIN → confirm new PIN`. Used when the user already
 * has an active PIN session but wants to set a new one.
 */
export default function PinResetPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const requestReset = useRequestPinReset();
  const confirmReset = useConfirmPinReset();

  const [step, setStep] = useState<Step>("request");
  const [code, setCode] = useState("");
  const [pin, setPin] = useState("");
  const [memo, setMemo] = useState("");

  const startReset = async () => {
    try {
      const r = await requestReset.mutateAsync();
      if (r.delivered) {
        toast.show({ kind: "info", title: "Код отправлен в Telegram" });
      } else {
        toast.show({
          kind: "error",
          title: "Бот не смог отправить вам сообщение",
          body: "Откройте Telegram, напишите /start боту и повторите.",
        });
      }
      setCode("");
      setStep("code");
    } catch (e) {
      haptic("error");
      const msg = (e as { message?: string }).message || "Не удалось запросить сброс";
      toast.show({ kind: "error", title: msg });
    }
  };

  const onCodeContinue = () => {
    if (code.length !== 6) return;
    setPin("");
    setMemo("");
    setStep("new");
  };

  const onPinComplete = async (value: string) => {
    if (step === "new") {
      setMemo(value);
      setPin("");
      setStep("confirm");
      return;
    }
    if (step === "confirm") {
      if (value !== memo) {
        haptic("error");
        toast.show({ kind: "error", title: "PIN не совпадает" });
        setPin("");
        setMemo("");
        setStep("new");
        return;
      }
      try {
        const t = await confirmReset.mutateAsync({ code, new_pin: memo });
        setPinToken(t.token, t.expires_at);
        haptic("success");
        toast.show({ kind: "success", title: "PIN успешно изменён" });
        navigate("/profile/settings");
      } catch (e) {
        const msg = (e as { message?: string }).message || "Не удалось сменить PIN";
        haptic("error");
        toast.show({ kind: "error", title: msg });
        setPin("");
        setMemo("");
        setCode("");
        setStep("code");
      }
    }
  };

  const titles: Record<Step, { title: string; subtitle: string }> = {
    request: {
      title: "Сброс PIN-кода",
      subtitle:
        "Нажмите кнопку ниже, чтобы получить 6-значный код подтверждения в Telegram-бот Garant.",
    },
    code: {
      title: "Введите код",
      subtitle: "Откройте чат с ботом и введите код из сообщения. Срок действия 10 минут.",
    },
    new: { title: "Новый PIN", subtitle: "Придумайте новые 4 цифры" },
    confirm: { title: "Подтвердите PIN", subtitle: "Введите новый PIN ещё раз" },
  };
  const heading = titles[step];

  return (
    <Page showBack onBack={() => navigate("/profile/settings")}>
      <div className="min-h-[80vh] flex flex-col items-center justify-center px-6 py-10">
        <button
          type="button"
          onClick={() => navigate("/profile/settings")}
          aria-label="Назад"
          className="self-start text-text-muted text-sm flex items-center gap-1 mb-6"
        >
          <ArrowLeft className="size-4" /> К настройкам
        </button>

        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.18 }}
            className="text-center mb-10 max-w-xs"
          >
            <h1 className="text-2xl font-semibold">{heading.title}</h1>
            <p className="text-text-muted mt-2 text-sm">{heading.subtitle}</p>
          </motion.div>
        </AnimatePresence>

        {step === "request" && (
          <div className="w-full max-w-xs flex flex-col items-center gap-3">
            <Button
              variant="primary"
              fullWidth
              disabled={requestReset.isPending}
              onClick={startReset}
            >
              {requestReset.isPending ? "Отправляем…" : "Запросить код"}
            </Button>
          </div>
        )}

        {step === "code" && (
          <div className="w-full max-w-xs flex flex-col items-center gap-3">
            <input
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              inputMode="numeric"
              autoFocus
              placeholder="000000"
              className="w-full text-center text-2xl tracking-[0.5em] bg-panel border border-border rounded-button py-3 outline-none focus:border-accent"
            />
            <Button variant="primary" fullWidth disabled={code.length !== 6} onClick={onCodeContinue}>
              Продолжить
            </Button>
            <button
              type="button"
              className="text-text-muted text-sm underline"
              onClick={startReset}
              disabled={requestReset.isPending}
            >
              Запросить новый код
            </button>
          </div>
        )}

        {(step === "new" || step === "confirm") && (
          <PinPad
            value={pin}
            onChange={setPin}
            onComplete={onPinComplete}
            disabled={confirmReset.isPending}
          />
        )}
      </div>
    </Page>
  );
}
