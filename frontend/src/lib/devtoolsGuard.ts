/**
 * Devtools / window-control guard.
 *
 * Hooks document-level keyboard and contextmenu listeners that
 * preventDefault on the shortcuts a Mini App user could otherwise use
 * to open the inspector or otherwise step outside the locked
 * fullscreen experience:
 *
 *   - F12               -> open browser devtools
 *   - Ctrl+Shift+I      -> open devtools (cross-browser)
 *   - Ctrl+Shift+J      -> open devtools console
 *   - Ctrl+Shift+C      -> element picker / inspector
 *   - Ctrl+U            -> view source
 *   - Ctrl+S            -> save page
 *   - Right-click       -> context menu (which exposes "Inspect")
 *   - F11               -> toggle browser fullscreen (we control fs)
 *
 * The guard is intentionally opt-in via :func:`installDevtoolsGuard`
 * so unit tests, the local dev server outside Telegram and any future
 * admin tooling can stay unaffected. Callers should mount it on app
 * boot and call the returned cleanup function on unmount.
 *
 * NOTE: this is a UX lock, not a security boundary. A determined user
 * can still open devtools through their OS menu. The goal is to match
 * the Telegram-Mini-App-style "kiosk window" experience the user
 * asked for, not to actually prevent inspection.
 */

const BLOCKED_LOWER_KEYS = new Set(["i", "j", "c", "u", "s"]);

function isBlockedKeydown(event: KeyboardEvent): boolean {
  // F12 alone — open devtools in every major browser.
  if (event.key === "F12") return true;
  // F11 — toggle browser fullscreen, we want Telegram fullscreen to win.
  if (event.key === "F11") return true;

  const ctrlLike = event.ctrlKey || event.metaKey;
  if (!ctrlLike) return false;

  const lower = event.key.toLowerCase();

  // Ctrl+Shift+(I|J|C) -> devtools variants.
  if (event.shiftKey && (lower === "i" || lower === "j" || lower === "c")) {
    return true;
  }
  // Ctrl+U -> view source. Ctrl+S -> save page. Ctrl+P -> print.
  if (BLOCKED_LOWER_KEYS.has(lower) && !event.shiftKey && !event.altKey) {
    // Ctrl+S triggers the browser's save-page dialog; Ctrl+U opens
    // view-source. Both step outside the Mini App, so block them.
    return lower === "u" || lower === "s";
  }
  return false;
}

function onKeyDown(event: KeyboardEvent) {
  if (isBlockedKeydown(event)) {
    event.preventDefault();
    event.stopPropagation();
  }
}

function onContextMenu(event: MouseEvent) {
  event.preventDefault();
}

/**
 * Install the keyboard + context-menu guards. Returns a cleanup
 * function that uninstalls them \u2014 callers (e.g. ``useEffect``) should
 * call it on unmount so React Strict Mode double-invocations don't
 * leave duplicate listeners attached.
 */
export function installDevtoolsGuard(): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("keydown", onKeyDown, { capture: true });
  window.addEventListener("contextmenu", onContextMenu, { capture: true });
  return () => {
    window.removeEventListener("keydown", onKeyDown, { capture: true } as EventListenerOptions);
    window.removeEventListener("contextmenu", onContextMenu, { capture: true } as EventListenerOptions);
  };
}

// Re-exported for unit testing without hitting the real ``window``.
export const __testing = { isBlockedKeydown };
