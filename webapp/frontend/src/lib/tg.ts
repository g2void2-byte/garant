/**
 * Thin wrapper around the Telegram WebApp script that is loaded in
 * `index.html`. Keeps the rest of the app decoupled from the global.
 */

type HapticStyle = "light" | "medium" | "heavy" | "soft" | "rigid";
type HapticNotification = "error" | "success" | "warning";

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: { user?: { id: number; username?: string; first_name?: string } };
  themeParams: Record<string, string>;
  ready: () => void;
  expand: () => void;
  close: () => void;
  isExpanded: boolean;
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
  } catch {
    /* noop */
  }
}

export function haptic(kind: "light" | "medium" | "heavy" | "success" | "error" | "warning" | "select") {
  if (!tg) return;
  try {
    if (kind === "select") tg.HapticFeedback.selectionChanged();
    else if (kind === "success" || kind === "error" || kind === "warning") tg.HapticFeedback.notificationOccurred(kind);
    else tg.HapticFeedback.impactOccurred(kind);
  } catch {
    /* noop */
  }
}

export function getInitData(): string {
  if (tg?.initData) return tg.initData;
  // Dev fallback so the UI renders outside of Telegram.
  if (typeof window !== "undefined") {
    const stored = window.localStorage.getItem("dev_init_data");
    if (stored) return stored;
  }
  return "";
}

export function getTelegramUser() {
  return tg?.initDataUnsafe?.user;
}

export function openTelegramLink(url: string) {
  if (tg) tg.openTelegramLink(url);
  else window.open(url, "_blank");
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
