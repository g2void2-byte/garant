/**
 * Audit L-15 — thin wrapper around ``Telegram.WebApp.showConfirm``.
 *
 * The Mini App used to call ``window.confirm`` directly from admin
 * pages; on the Telegram WebView that blocks the JS thread, can't be
 * styled, and on iOS / mobile clients renders as a system-grey dialog
 * that visually disagrees with the rest of the app. ``showConfirm`` is
 * supported on every Mini App client (Bot API 6.2+) and looks native
 * on each platform.
 *
 * We keep ``window.confirm`` as a fallback for:
 *   - dev mode running outside Telegram (``tg`` is ``undefined``),
 *   - the legacy Telegram clients that lack ``showConfirm``
 *     (Bot API < 6.2 — pre-2022 desktop builds).
 *
 * ``confirmDialog`` returns a Promise so callers can use ``await``.
 */
import { tg } from "./tg";

interface TelegramWebAppWithConfirm {
  showConfirm?: (message: string, callback: (ok: boolean) => void) => void;
}

export function confirmDialog(message: string): Promise<boolean> {
  const tgConfirm = tg as TelegramWebAppWithConfirm | undefined;
  if (tgConfirm?.showConfirm) {
    return new Promise<boolean>((resolve) => {
      try {
        tgConfirm.showConfirm!(message, (ok) => resolve(Boolean(ok)));
      } catch (err) {
        // showConfirm exists but threw (rare; e.g. invalid arg, too
        // long message). Fall back to the synchronous browser dialog
        // so the user can still complete the action.
        if (import.meta.env.DEV) {
          console.warn("confirmDialog: showConfirm threw, falling back", err);
        }
        resolve(typeof window !== "undefined" ? window.confirm(message) : false);
      }
    });
  }
  // No Telegram WebApp (dev preview / unit tests) — use the synchronous
  // browser dialog and resolve the Promise immediately.
  if (typeof window !== "undefined") {
    return Promise.resolve(window.confirm(message));
  }
  return Promise.resolve(false);
}
