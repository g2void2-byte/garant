import { ChevronDown } from "lucide-react";
import { haptic, isMobile, minimizeApp } from "@/lib/tg";

/**
 * Floating "minimize" button — mobile only.
 *
 * Telegram Mini Apps run fullscreen on mobile, which hides Telegram's
 * own header (the one with the chevron-down / close affordance). The
 * user asked for a built-in equivalent so the bot remains exitable on
 * mobile devices. On desktop the button is hidden — the Telegram
 * Desktop window already provides a close affordance and the user
 * explicitly asked for the PC variant to stay locked down.
 *
 * Position: fixed top-right with safe-area inset, high z-index so it
 * stays above page content but below modal overlays (which use
 * ``z-[80+]``).
 */
export function MinimizeButton() {
  if (!isMobile()) return null;

  return (
    <button
      type="button"
      onClick={() => {
        haptic("light");
        minimizeApp();
      }}
      aria-label="Свернуть приложение"
      title="Свернуть"
      className="fixed top-2 right-2 z-50 flex h-10 w-10 items-center justify-center rounded-full bg-panel/80 text-text shadow-lg backdrop-blur-sm active:scale-95 transition-transform"
      style={{ top: "max(env(safe-area-inset-top, 0px), 8px)" }}
    >
      <ChevronDown className="size-5" strokeWidth={2.25} />
    </button>
  );
}
