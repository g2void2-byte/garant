import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useCheckPin } from "@/api/hooks";
import { PinPad } from "@/components/ui/PinPad";
import { PinResetPaywallModal } from "@/components/PinResetPaywallModal";
import { useToast } from "@/components/ui/Toast";
import { cn } from "@/lib/cn";
import { usePresence } from "@/lib/animate";
import { setPinToken } from "@/lib/pin";
import { haptic } from "@/lib/tg";

interface PinPromptModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  title?: string;
  subtitle?: string;
}

/**
 * Re-prompt the user for their 4-digit PIN before a sensitive action
 * (creating a deal, requesting a withdrawal). The PinGate at the top
 * of the app only runs once per ``session_ttl_seconds`` window, so a
 * lukewarm session can otherwise authorise spend operations without
 * a fresh confirmation — this modal closes that gap.
 *
 * Successful ``POST /api/pin/check`` refreshes the locally-stored PIN
 * token and then fires ``onSuccess()`` so the caller can proceed with
 * the mutation it was guarding.
 */
export function PinPromptModal({
  open,
  onClose,
  onSuccess,
  title = "Подтвердите PIN-код",
  subtitle = "Введите 4 цифры, чтобы продолжить",
}: PinPromptModalProps) {
  const toast = useToast();
  const check = useCheckPin();
  const [pin, setPin] = useState("");
  const [paywallOpen, setPaywallOpen] = useState(false);
  const { mounted, visible } = usePresence(open, 200);

  useEffect(() => {
    if (!open) {
      setPin("");
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function handleComplete(full: string) {
    try {
      const token = await check.mutateAsync(full);
      setPinToken(token.token, token.expires_at);
      haptic("success");
      setPin("");
      onSuccess();
    } catch (e: unknown) {
      haptic("error");
      toast.show({
        kind: "error",
        title: (e as Error)?.message || "Неверный PIN",
      });
      setPin("");
    }
  }

  if (!mounted) return null;

  // V14-card — render via React portal so the modal escapes any
  // ancestor with a non-``none`` transform (e.g. ``<Page>``'s
  // ``animate-fadein``) which would otherwise turn ``fixed inset-0``
  // into a containing block against the short Page div and clip the
  // dialog off the top of the viewport.
  const body = (
    <>
      <div
        className={cn(
          "fixed inset-0 z-[60] bg-black/70 backdrop-blur-sm transition-opacity duration-200",
          visible ? "opacity-100" : "opacity-0",
        )}
        onClick={onClose}
      />
      <div
        className={cn(
          "fixed inset-0 z-[61] grid place-items-center p-4 pointer-events-none",
          visible ? "opacity-100" : "opacity-0",
          "transition-opacity duration-200",
        )}
      >
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="pin-prompt-title"
          data-testid="pin-prompt"
          className={cn(
            "pointer-events-auto w-full max-w-sm rounded-3xl bg-panel border border-border shadow-pop p-6",
            "transform transition-all duration-200",
            visible ? "scale-100 opacity-100" : "scale-95 opacity-0",
          )}
        >
          <div className="flex items-start justify-between">
            <div className="min-w-0">
              <h2
                id="pin-prompt-title"
                className="text-[20px] font-semibold tracking-tight text-text"
              >
                {title}
              </h2>
              <p className="text-text-muted mt-1 text-[14px]">{subtitle}</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Закрыть"
              className="size-9 -mr-1 -mt-1 grid place-items-center rounded-full text-text-muted hover:bg-secondary active:scale-95 transition"
            >
              <X className="size-4" />
            </button>
          </div>
          <div className="mt-6">
            <PinPad
              value={pin}
              onChange={setPin}
              onComplete={handleComplete}
              disabled={check.isPending}
            />
          </div>
          <div className="mt-4 text-center">
            <button
              type="button"
              onClick={() => setPaywallOpen(true)}
              className="text-accent text-[13px] underline"
            >
              Забыли PIN?
            </button>
          </div>
        </div>
      </div>

      <PinResetPaywallModal
        open={paywallOpen}
        onClose={() => setPaywallOpen(false)}
        onPaid={(res) => {
          setPaywallOpen(false);
          // Close the PIN prompt too — the user now has a fresh
          // reset code in Telegram and needs to go through the
          // full PIN-reset flow on the lock screen, not type their
          // (now-unknown) PIN here. We surface a clear toast so
          // they know what to do next.
          onClose();
          toast.show({
            kind: "info",
            title: res.delivered
              ? "Код отправлен в Telegram"
              : "Код выписан, но Telegram-сообщение не доставлено",
            body:
              "Перезайдите на главный экран и нажмите «Забыли PIN?»,"
              + " чтобы ввести 6-значный код.",
          });
        }}
        title="Без PIN-кода вывод недоступен"
      />
    </>
  );

  if (typeof document === "undefined") return body;
  return createPortal(body, document.body);
}
