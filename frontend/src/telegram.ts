/**
 * Telegram WebApp bridge.
 *
 * Provides a tiny wrapper around `window.Telegram.WebApp` so the rest of the
 * app can stay agnostic about whether it's running inside Telegram or a
 * plain browser (which is useful while developing).
 */

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

export interface TelegramUser {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  language_code?: string;
}

export interface TelegramWebApp {
  initData: string;
  initDataUnsafe?: { user?: TelegramUser };
  colorScheme: "light" | "dark";
  themeParams: Record<string, string>;
  isExpanded: boolean;
  viewportHeight: number;
  ready(): void;
  expand(): void;
  close(): void;
  enableClosingConfirmation(): void;
  setHeaderColor(color: string): void;
  setBackgroundColor(color: string): void;
  HapticFeedback?: {
    impactOccurred(style: "light" | "medium" | "heavy" | "rigid" | "soft"): void;
    notificationOccurred(type: "error" | "success" | "warning"): void;
    selectionChanged(): void;
  };
  showAlert?(text: string): void;
  showConfirm?(text: string, cb: (ok: boolean) => void): void;
}

const DEV_FALLBACK_USER: TelegramUser = {
  id: 4242,
  first_name: "Devin",
  last_name: "Dev",
  username: "devin_dev",
  photo_url: "",
};

export function getTelegram(): TelegramWebApp | undefined {
  return window.Telegram?.WebApp;
}

export function getInitData(): string {
  const tg = getTelegram();
  if (tg?.initData) return tg.initData;

  // Dev fallback — emulate a Telegram payload without a hash so the backend
  // (configured without BOT_TOKEN in development) still authenticates us.
  //
  // For local multi-user testing, append ?as=<tg_id>&name=<first>&u=<username>
  // to the URL once; the identity is stashed in sessionStorage so it survives
  // React-Router navigations within the same tab.
  let user: TelegramUser = DEV_FALLBACK_USER;
  try {
    const url = new URL(window.location.href);
    const asId = url.searchParams.get("as");
    if (asId) {
      const overrideUser: TelegramUser = {
        id: Number(asId),
        first_name: url.searchParams.get("name") ?? `User ${asId}`,
        username: url.searchParams.get("u") ?? undefined,
        photo_url: "",
      };
      window.sessionStorage.setItem("autogarant.dev_user", JSON.stringify(overrideUser));
      user = overrideUser;
    } else {
      const stashed = window.sessionStorage.getItem("autogarant.dev_user");
      if (stashed) user = JSON.parse(stashed) as TelegramUser;
    }
  } catch {
    user = DEV_FALLBACK_USER;
  }
  const params = new URLSearchParams();
  params.set("user", JSON.stringify(user));
  params.set("auth_date", String(Math.floor(Date.now() / 1000)));
  return params.toString();
}

export function getUser(): TelegramUser | undefined {
  return getTelegram()?.initDataUnsafe?.user ?? DEV_FALLBACK_USER;
}

export function haptic(style: "light" | "medium" | "heavy" = "light"): void {
  getTelegram()?.HapticFeedback?.impactOccurred(style);
}

export function selectionChanged(): void {
  getTelegram()?.HapticFeedback?.selectionChanged();
}

export function notify(type: "success" | "warning" | "error"): void {
  getTelegram()?.HapticFeedback?.notificationOccurred(type);
}

export function setupTelegram(): void {
  const tg = getTelegram();
  if (!tg) return;
  tg.ready();
  tg.expand();
  tg.setHeaderColor("#0b0b0e");
  tg.setBackgroundColor("#0b0b0e");
}
