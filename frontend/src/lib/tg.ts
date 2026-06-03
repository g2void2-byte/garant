/**
 * Thin wrapper around the Telegram WebApp script that is loaded in
 * `index.html`. Keeps the rest of the app decoupled from the global.
 */

import { useEffect, useState } from "react";

import { safeLocalStorageGet } from "@/lib/storage";

type HapticStyle = "light" | "medium" | "heavy" | "soft" | "rigid";
type HapticNotification = "error" | "success" | "warning";

// Telegram client platform identifiers as reported by ``Telegram.WebApp.platform``.
// Mobile clients: android / android_x / ios. Everything else (tdesktop, macos,
// weba, webk, windows, linux, unknown) we treat as desktop / web for layout
// purposes — the Mini App lives in a separate floating window there and needs
// the lock-down (fullscreen + no F12) treatment.
const MOBILE_PLATFORMS = new Set(["android", "android_x", "ios"]);

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: {
    user?: {
      id: number;
      username?: string;
      first_name?: string;
      last_name?: string;
      photo_url?: string;
    };
  };
  themeParams: Record<string, string>;
  platform?: string;
  version?: string;
  isVersionAtLeast?: (v: string) => boolean;
  ready: () => void;
  expand: () => void;
  close: () => void;
  isExpanded: boolean;
  // V13.2 — in Telegram Desktop the iframe is fixed-height; ``100dvh``
  // does not match the real Mini App viewport until ``expand()`` is
  // called AND ``viewportChanged`` fires. ``Sheet`` reads these via
  // ``useTelegramViewport`` so the bottom-sheet never overflows the
  // iframe and disappears off-screen.
  viewportHeight?: number;
  viewportStableHeight?: number;
  isFullscreen?: boolean;
  requestFullscreen?: () => void;
  exitFullscreen?: () => void;
  disableVerticalSwipes?: () => void;
  enableClosingConfirmation?: () => void;
  lockOrientation?: () => void;
  offEvent?: (event: string, handler: () => void) => void;
  HapticFeedback: {
    impactOccurred: (style: HapticStyle) => void;
    notificationOccurred: (type: HapticNotification) => void;
    selectionChanged: () => void;
  };
  BackButton: {
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
  MainButton: {
    setText: (t: string) => void;
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
    enable: () => void;
    disable: () => void;
    showProgress: (leave?: boolean) => void;
    hideProgress: () => void;
    setParams: (p: {
      text?: string;
      color?: string;
      text_color?: string;
      is_active?: boolean;
      is_visible?: boolean;
    }) => void;
  };
  CloudStorage?: {
    getItem: (key: string, cb: (err: string | null, value: string) => void) => void;
    setItem: (key: string, value: string, cb?: (err: string | null) => void) => void;
  };
  openTelegramLink: (url: string) => void;
  openLink: (url: string) => void;
  onEvent: (event: string, handler: () => void) => void;
}

// Re-exported so React components can do feature detection without
// importing ``window.Telegram`` directly.
export type { TelegramWebApp };

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

export const tg: TelegramWebApp | undefined = typeof window !== "undefined" ? window.Telegram?.WebApp : undefined;

export function initTelegram() {
  if (!tg) return;
  try {
    tg.ready();
    tg.expand();
  } catch (err) {
    // Swallowing this used to mask Telegram-side regressions
    // entirely: surface it to the browser console so operators can
    // notice when ``ready`` / ``expand`` start failing.
    // L-18: gate the dev-only diagnostics on ``import.meta.env.DEV``
    // so Vite's dead-code elimination strips them from the production
    // bundle (the Telegram WebView still has a console but we don't
    // want to ship noise to it).
    if (import.meta.env.DEV) {
      console.warn("initTelegram: Telegram.WebApp call failed", err);
    }
  }
  lockToFullscreen();
}

/**
 * Returns true when the Mini App is running inside a mobile Telegram
 * client (Android / iOS). Desktop, web and "unknown" all return false.
 *
 * Used to decide whether to render the in-app minimize button — on PC
 * Telegram already provides window controls, on mobile the bot lives
 * fullscreen with no native chrome so we need our own.
 */
export function isMobile(): boolean {
  const platform = tg?.platform;
  if (!platform) return false;
  return MOBILE_PLATFORMS.has(platform.toLowerCase());
}

/**
 * Asks Telegram to put the Mini App into fullscreen mode and keep it
 * there. Telegram Bot API 8.0+ method; older clients silently no-op.
 *
 * We also wire up the ``fullscreenChanged`` event so if the user (or a
 * stray gesture) exits fullscreen we immediately re-request it — this
 * is what gives the "no way to shrink the window" behaviour the user
 * asked for.
 *
 * Additionally calls ``disableVerticalSwipes`` so a downward swipe on
 * mobile doesn't dismiss the Mini App, and ``enableClosingConfirmation``
 * so a stray Esc / window close doesn't lose user state.
 */
let fullscreenListenerInstalled = false;
export function lockToFullscreen() {
  if (!tg) return;
  try {
    tg.disableVerticalSwipes?.();
    tg.enableClosingConfirmation?.();
    tg.requestFullscreen?.();
  } catch (err) {
    // L-18: dev-only diagnostics; stripped from the production bundle.
    if (import.meta.env.DEV) {
      console.warn("lockToFullscreen: Telegram.WebApp call failed", err);
    }
  }
  if (fullscreenListenerInstalled) return;
  try {
    tg.onEvent("fullscreenChanged", () => {
      // Telegram fires this on both enter and exit. If the new state
      // is "not fullscreen" the user (or the platform) just left
      // fullscreen — re-request immediately to keep the lock in place.
      if (tg && tg.isFullscreen === false) {
        try {
          tg.requestFullscreen?.();
        } catch (err) {
          // L-18: dev-only diagnostics; stripped from the production
          // bundle so a flaky fullscreen API doesn't spam Telegram
          // WebView consoles.
          if (import.meta.env.DEV) {
            console.warn("lockToFullscreen: re-request failed", err);
          }
        }
      }
    });
    fullscreenListenerInstalled = true;
  } catch (err) {
    // L-18: dev-only diagnostics; stripped from the production bundle.
    if (import.meta.env.DEV) {
      console.warn("lockToFullscreen: onEvent failed", err);
    }
  }
}

/**
 * Closes the Mini App, which on Telegram clients effectively
 * "minimizes" it — the user can re-open the bot from chat and resume
 * where they left off. Used by the mobile-only minimize button.
 */
export function minimizeApp() {
  if (!tg) return;
  try {
    tg.exitFullscreen?.();
  } catch (err) {
    // L-18: dev-only diagnostics; stripped from the production bundle.
    if (import.meta.env.DEV) {
      console.warn("minimizeApp: exitFullscreen failed", err);
    }
  }
  try {
    tg.close();
  } catch (err) {
    // L-18: dev-only diagnostics; stripped from the production bundle.
    if (import.meta.env.DEV) {
      console.warn("minimizeApp: close failed", err);
    }
  }
}

// Test-only hook: reset module-level state between tests so installing
// the fullscreen listener twice in a row in a single test process
// doesn't silently no-op the second call.
export function __resetTgModuleStateForTests() {
  fullscreenListenerInstalled = false;
}

export function haptic(kind: "light" | "medium" | "heavy" | "success" | "error" | "warning" | "select") {
  if (!tg) return;
  try {
    if (kind === "select") tg.HapticFeedback.selectionChanged();
    else if (kind === "success" || kind === "error" || kind === "warning") tg.HapticFeedback.notificationOccurred(kind);
    else tg.HapticFeedback.impactOccurred(kind);
  } catch (err) {
    // Haptics are best-effort — old Telegram clients don't support
    // them — but we still want a console trail when they fail.
    // L-18: dev-only diagnostics; stripped from the production bundle.
    if (import.meta.env.DEV) {
      console.warn("haptic: Telegram.WebApp call failed", kind, err);
    }
  }
}

export function getInitData(): string {
  if (tg?.initData) return tg.initData;
  // Dev-only fallback so the UI renders outside of Telegram during
  // local development. The ``import.meta.env.DEV`` check is replaced
  // with a literal ``false`` by Vite's build pipeline in production,
  // so dead-code elimination strips the localStorage read from the
  // shipped bundle entirely. Without the guard a stale or attacker-
  // controlled ``dev_init_data`` value would let a compromised JS
  // context bypass server-side auth whenever the backend has
  // ``allow_unsigned_init_data`` enabled.
  if (import.meta.env.DEV) {
    const stored = safeLocalStorageGet("dev_init_data");
    if (stored) return stored;
  }
  return "";
}

export function getTelegramUser() {
  return tg?.initDataUnsafe?.user;
}

export function openExternalLink(url: string) {
  // V12-UI — wraps ``Telegram.WebApp.openLink`` so forum links (clearnet
  // /tor URLs entered by the user on the AddForumPage) open in the
  // Telegram in-app browser. Falls back to ``window.open`` when the TMA
  // is being inspected outside of Telegram (e.g. desktop preview).
  //
  // Audit H-1 — gate every call through ``isSafeLink`` so a hostile or
  // mis-validated server value (``WalletDeposit.pay_url``, forum mirror
  // URL, support DM link) can't smuggle ``javascript:`` / ``data:`` /
  // ``vbscript:`` / ``file:`` schemes into ``tg.openLink`` and execute
  // attacker JS inside the Mini App context. ``openTelegramLink`` had
  // the same guard since L-13; ``openExternalLink`` did not, which left
  // every non-Telegram URL surface (forum links, pay URLs, support
  // references) unprotected.
  if (!isSafeLink(url)) return;
  if (tg && tg.openLink) {
    tg.openLink(url);
    return;
  }
  if (typeof window !== "undefined") window.open(url, "_blank", "noopener,noreferrer");
}

export function openPaymentLink(url: string) {
  const safe = parseSafeLink(url);
  if (!safe) return;
  const href = safe.toString();
  if (safe.hostname === "t.me") {
    openTelegramLink(href);
    return;
  }
  openExternalLink(href);
}

// Audit L-13 / H-1 — schemes we allow to flow through
// ``openTelegramLink`` / ``openExternalLink``. Anything else
// (``javascript:``, ``data:``, ``vbscript:``, ``file:`` …) is refused
// before it can reach ``tg.openTelegramLink`` / ``tg.openLink`` /
// ``window.open`` so an attacker who manages to inject a hostile URL
// into a server-controlled field (e.g. ``WalletDeposit.pay_url``, a
// username, a forum mirror) can't escalate to in-context script
// execution against the TMA.
const _SAFE_LINK_SCHEMES = new Set(["http:", "https:"]);

function parseSafeLink(url: string): URL | null {
  if (!url) return null;
  for (let i = 0; i < url.length; i += 1) {
    const code = url.charCodeAt(i);
    if (code < 0x20 || code === 0x7f || url[i] === " ") return null;
  }
  try {
    const u = new URL(url);
    if (!_SAFE_LINK_SCHEMES.has(u.protocol)) return null;
    if (!u.hostname || u.username || u.password) return null;
    return u;
  } catch {
    return null;
  }
}

function isSafeLink(url: string): boolean {
  return parseSafeLink(url) !== null;
}

export function isSafeExternalLink(url: string): boolean {
  return isSafeLink(url);
}

export function openTelegramLink(url: string) {
  // Audit L-13 — reject anything that isn't a plain ``http(s):`` URL
  // before delegating. ``tg.openTelegramLink`` itself only accepts
  // ``t.me/*`` URLs (anything else raises ``WebAppTgUrlInvalid`` on the
  // Telegram client side), so callers must route non-t.me invoice URLs
  // (e.g. Crystalpay ``pay.crystalpay.io/...``) through ``openExternalLink``
  // instead. CryptoBot invoice URLs are ``https://t.me/CryptoBot?...`` and
  // do work here.
  const safe = parseSafeLink(url);
  if (safe?.hostname !== "t.me") return;
  const href = safe.toString();
  // Audit M-7 — the fallback path is only taken outside of Telegram
  // (desktop preview / unit tests). Match ``openExternalLink`` and pass
  // ``noopener,noreferrer`` so the destination page can't reach back
  // through ``window.opener``.
  if (tg) tg.openTelegramLink(href);
  else if (typeof window !== "undefined") window.open(href, "_blank", "noopener,noreferrer");
}

export function showBackButton(onClick: () => void) {
  if (!tg) return () => {};
  tg.BackButton.onClick(onClick);
  tg.BackButton.show();
  return () => {
    tg.BackButton.offClick(onClick);
    tg.BackButton.hide();
  };
}

export function showMainButton(text: string, onClick: () => void) {
  if (!tg) return () => {};
  tg.MainButton.setParams({ text, is_visible: true, is_active: true, color: "#FFD60A", text_color: "#0E0E0F" });
  tg.MainButton.onClick(onClick);
  return () => {
    tg.MainButton.offClick(onClick);
    tg.MainButton.hide();
  };
}

/**
 * Returns the live Telegram Mini App viewport height in CSS pixels.
 *
 * V13.2 — in Telegram Desktop the Mini App is hosted in an iframe
 * whose height does not match ``window.innerHeight`` and is NOT
 * what CSS ``100dvh`` resolves to until the Mini App calls
 * ``WebApp.expand()`` AND Telegram fires ``viewportChanged``. Using
 * ``min-h-[80dvh]`` on a bottom sheet there produces a sheet
 * taller than the iframe — the bottom-anchored sheet renders above
 * the visible area and the user sees an empty grey strip.
 *
 * This hook:
 *
 * * Returns ``null`` in environments without Telegram WebApp (Vite
 *   dev server, jsdom tests). Callers fall back to a static CSS
 *   max-height (``min(92dvh, 92vh)``) in that case.
 * * Calls ``WebApp.expand()`` once at mount so the viewport jumps
 *   to its real max immediately, before the sheet animates in.
 * * Subscribes to ``viewportChanged`` so the sheet shrinks when
 *   Telegram itself shrinks the iframe (mobile keyboard, app
 *   minimize), then unsubscribes on unmount via
 *   ``offEvent`` when available — older clients without ``offEvent``
 *   leak the listener but Telegram's dispatcher is keyed by
 *   reference and the same handler being re-installed by a remount
 *   is a no-op.
 */
export function useTelegramViewport(): number | null {
  // Read ``window.Telegram`` lazily here rather than reusing the
  // module-level ``tg`` constant: ``tg`` is evaluated at module load
  // time, so in jsdom-based tests where ``window.Telegram`` is set
  // BEFORE render but AFTER the module is imported the constant
  // would still be ``undefined`` and the hook would never engage.
  // Reading at call time also lets the legacy ``initTelegram`` /
  // ``lockToFullscreen`` paths (which run before any React render)
  // settle ``isExpanded`` first.
  const getApp = (): TelegramWebApp | undefined =>
    typeof window !== "undefined" ? window.Telegram?.WebApp : undefined;

  const [vh, setVh] = useState<number | null>(() => {
    const app = getApp();
    if (!app) return null;
    return app.viewportStableHeight ?? app.viewportHeight ?? null;
  });

  useEffect(() => {
    const app = getApp();
    if (!app) return;
    try {
      app.expand();
    } catch {
      // Older Telegram clients can throw on ``expand`` if the Mini App
      // is already fullscreen / closed. Best-effort.
    }
    const handler = () => {
      setVh(app.viewportStableHeight ?? app.viewportHeight ?? null);
    };
    try {
      app.onEvent("viewportChanged", handler);
    } catch {
      // ``onEvent`` is a no-op on very old Telegram clients; the
      // initial ``setVh`` from ``useState`` covers the static case.
    }
    return () => {
      try {
        app.offEvent?.("viewportChanged", handler);
      } catch {
        // see ``onEvent`` comment.
      }
    };
  }, []);

  return vh;
}
