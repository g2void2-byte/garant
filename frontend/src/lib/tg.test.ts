import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Stand-in for the Telegram WebApp global. Each test rewrites the
// fields it cares about, then dynamically re-imports ./tg so the
// module captures the fresh ``window.Telegram.WebApp`` reference.
type FakeWebApp = {
  initData: string;
  initDataUnsafe: { user?: { id: number } };
  themeParams: Record<string, string>;
  isExpanded: boolean;
  isFullscreen: boolean;
  platform: string;
  ready: ReturnType<typeof vi.fn>;
  expand: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  requestFullscreen: ReturnType<typeof vi.fn>;
  exitFullscreen: ReturnType<typeof vi.fn>;
  disableVerticalSwipes: ReturnType<typeof vi.fn>;
  enableClosingConfirmation: ReturnType<typeof vi.fn>;
  HapticFeedback: {
    impactOccurred: ReturnType<typeof vi.fn>;
    notificationOccurred: ReturnType<typeof vi.fn>;
    selectionChanged: ReturnType<typeof vi.fn>;
  };
  BackButton: {
    show: ReturnType<typeof vi.fn>;
    hide: ReturnType<typeof vi.fn>;
    onClick: ReturnType<typeof vi.fn>;
    offClick: ReturnType<typeof vi.fn>;
  };
  MainButton: {
    setParams: ReturnType<typeof vi.fn>;
    onClick: ReturnType<typeof vi.fn>;
    offClick: ReturnType<typeof vi.fn>;
    hide: ReturnType<typeof vi.fn>;
  };
  openTelegramLink: ReturnType<typeof vi.fn>;
  openLink: ReturnType<typeof vi.fn>;
  onEvent: ReturnType<typeof vi.fn>;
  _fullscreenChangedHandler?: () => void;
};

function buildFakeWebApp(platform: string): FakeWebApp {
  const fake: FakeWebApp = {
    initData: "",
    initDataUnsafe: {},
    themeParams: {},
    isExpanded: false,
    isFullscreen: false,
    platform,
    ready: vi.fn(),
    expand: vi.fn(),
    close: vi.fn(),
    requestFullscreen: vi.fn(),
    exitFullscreen: vi.fn(),
    disableVerticalSwipes: vi.fn(),
    enableClosingConfirmation: vi.fn(),
    HapticFeedback: {
      impactOccurred: vi.fn(),
      notificationOccurred: vi.fn(),
      selectionChanged: vi.fn(),
    },
    BackButton: { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() },
    MainButton: { setParams: vi.fn(), onClick: vi.fn(), offClick: vi.fn(), hide: vi.fn() },
    openTelegramLink: vi.fn(),
    openLink: vi.fn(),
    onEvent: vi.fn((event: string, handler: () => void) => {
      if (event === "fullscreenChanged") fake._fullscreenChangedHandler = handler;
    }),
  };
  return fake;
}

async function importTgWithFake(platform: string) {
  const fake = buildFakeWebApp(platform);
  (window as unknown as { Telegram?: { WebApp: FakeWebApp } }).Telegram = { WebApp: fake };
  vi.resetModules();
  const mod = await import("./tg");
  mod.__resetTgModuleStateForTests();
  return { fake, mod };
}

afterEach(() => {
  (window as unknown as { Telegram?: { WebApp: FakeWebApp } }).Telegram = undefined;
  vi.resetModules();
});

describe("isMobile", () => {
  it.each([
    ["android", true],
    ["android_x", true],
    ["ios", true],
    ["tdesktop", false],
    ["macos", false],
    ["weba", false],
    ["webk", false],
    ["windows", false],
    ["linux", false],
    ["unknown", false],
  ])("platform=%s -> %s", async (platform, expected) => {
    const { mod } = await importTgWithFake(platform);
    expect(mod.isMobile()).toBe(expected);
  });
});

describe("initTelegram + lockToFullscreen", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  it("requests fullscreen, disables vertical swipes, enables closing confirmation", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    mod.initTelegram();

    expect(fake.ready).toHaveBeenCalled();
    expect(fake.expand).toHaveBeenCalled();
    expect(fake.disableVerticalSwipes).toHaveBeenCalled();
    expect(fake.enableClosingConfirmation).toHaveBeenCalled();
    expect(fake.requestFullscreen).toHaveBeenCalled();
    expect(fake.onEvent).toHaveBeenCalledWith("fullscreenChanged", expect.any(Function));
  });

  it("re-requests fullscreen when the user exits", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    mod.initTelegram();
    expect(fake.requestFullscreen).toHaveBeenCalledTimes(1);

    // Simulate Telegram firing fullscreenChanged with the app now NOT in fullscreen.
    fake.isFullscreen = false;
    fake._fullscreenChangedHandler?.();
    expect(fake.requestFullscreen).toHaveBeenCalledTimes(2);

    // Going to fullscreen should NOT re-trigger (we'd loop otherwise).
    fake.isFullscreen = true;
    fake._fullscreenChangedHandler?.();
    expect(fake.requestFullscreen).toHaveBeenCalledTimes(2);
  });
});

describe("minimizeApp", () => {
  it("exits fullscreen then closes the Mini App", async () => {
    const { fake, mod } = await importTgWithFake("android");
    mod.minimizeApp();
    expect(fake.exitFullscreen).toHaveBeenCalled();
    expect(fake.close).toHaveBeenCalled();
  });

  it("is a no-op when Telegram is unavailable", async () => {
    (window as unknown as { Telegram?: unknown }).Telegram = undefined;
    vi.resetModules();
    const mod = await import("./tg");
    expect(() => mod.minimizeApp()).not.toThrow();
  });
});

describe("haptic", () => {
  it.each([
    ["light", "impactOccurred"],
    ["medium", "impactOccurred"],
    ["heavy", "impactOccurred"],
  ] as const)("kind=%s -> %s", async (kind, method) => {
    const { fake, mod } = await importTgWithFake("ios");
    mod.haptic(kind);
    const fb = fake.HapticFeedback as unknown as Record<string, ReturnType<typeof vi.fn>>;
    expect(fb[method]).toHaveBeenCalled();
  });

  it.each([
    ["success"],
    ["error"],
    ["warning"],
  ] as const)("kind=%s routes to notificationOccurred", async (kind) => {
    const { fake, mod } = await importTgWithFake("ios");
    mod.haptic(kind);
    expect(fake.HapticFeedback.notificationOccurred).toHaveBeenCalledWith(kind);
  });

  it("kind=select routes to selectionChanged", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    mod.haptic("select");
    expect(fake.HapticFeedback.selectionChanged).toHaveBeenCalled();
  });

  it("is a no-op when Telegram is unavailable", async () => {
    (window as unknown as { Telegram?: unknown }).Telegram = undefined;
    vi.resetModules();
    const mod = await import("./tg");
    expect(() => mod.haptic("light")).not.toThrow();
  });

  it("swallows errors thrown by the Telegram global", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { fake, mod } = await importTgWithFake("ios");
    fake.HapticFeedback.impactOccurred.mockImplementation(() => {
      throw new Error("legacy client");
    });
    expect(() => mod.haptic("light")).not.toThrow();
  });
});

describe("getInitData", () => {
  it("returns Telegram.WebApp.initData when present", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    fake.initData = "user=%7B%22id%22%3A1%7D&hash=abc";
    expect(mod.getInitData()).toBe("user=%7B%22id%22%3A1%7D&hash=abc");
  });

  it("returns an empty string when Telegram has no initData and no dev fallback exists", async () => {
    const { mod } = await importTgWithFake("ios");
    window.localStorage.clear();
    expect(mod.getInitData()).toBe("");
  });

  it("falls back to localStorage 'dev_init_data' in DEV builds", async () => {
    window.localStorage.setItem("dev_init_data", "dev-fallback-token");
    const { mod } = await importTgWithFake("ios");
    expect(mod.getInitData()).toBe("dev-fallback-token");
    window.localStorage.clear();
  });
});

describe("getTelegramUser", () => {
  it("returns the unsafe user when Telegram exposes it", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    fake.initDataUnsafe = { user: { id: 42 } };
    expect(mod.getTelegramUser()).toEqual({ id: 42 });
  });

  it("returns undefined when Telegram is unavailable", async () => {
    (window as unknown as { Telegram?: unknown }).Telegram = undefined;
    vi.resetModules();
    const mod = await import("./tg");
    expect(mod.getTelegramUser()).toBeUndefined();
  });
});

describe("openExternalLink", () => {
  it("delegates to Telegram.WebApp.openLink when available", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    mod.openExternalLink("https://example.com");
    expect(fake.openLink).toHaveBeenCalledWith("https://example.com");
  });

  it("falls back to window.open with noopener,noreferrer when Telegram is unavailable", async () => {
    (window as unknown as { Telegram?: unknown }).Telegram = undefined;
    vi.resetModules();
    const mod = await import("./tg");
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    mod.openExternalLink("https://example.com");
    expect(openSpy).toHaveBeenCalledWith("https://example.com", "_blank", "noopener,noreferrer");
    openSpy.mockRestore();
  });

  it.each([
    ["javascript:alert(1)"],
    ["JavaScript:alert(1)"],
    ["data:text/html,<script>alert(1)</script>"],
    ["vbscript:msgbox"],
    ["file:///etc/passwd"],
    ["not-a-url"],
    [""],
  ])("refuses to open unsafe URL %s", async (badUrl) => {
    // Audit H-1 — only ``http(s):`` URLs are allowed through. The
    // forum / pay-URL surface used to flow into ``tg.openLink``
    // without the scheme check that ``openTelegramLink`` already
    // had, leaving a script-execution gap inside the Mini App.
    const { fake, mod } = await importTgWithFake("ios");
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    mod.openExternalLink(badUrl);
    expect(fake.openLink).not.toHaveBeenCalled();
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("refuses unsafe URLs in the no-Telegram fallback too", async () => {
    (window as unknown as { Telegram?: unknown }).Telegram = undefined;
    vi.resetModules();
    const mod = await import("./tg");
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    mod.openExternalLink("javascript:alert(1)");
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });
});

describe("openTelegramLink", () => {
  it("delegates to Telegram.WebApp.openTelegramLink when available", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    mod.openTelegramLink("https://t.me/test");
    expect(fake.openTelegramLink).toHaveBeenCalledWith("https://t.me/test");
  });

  it("falls back to window.open with noopener,noreferrer when Telegram is unavailable", async () => {
    (window as unknown as { Telegram?: unknown }).Telegram = undefined;
    vi.resetModules();
    const mod = await import("./tg");
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    mod.openTelegramLink("https://t.me/test");
    // Audit M-7 — the fallback path opens links outside Telegram (desktop
    // preview / tests). We must pass ``noopener,noreferrer`` so the target
    // page can't reach back through ``window.opener``.
    expect(openSpy).toHaveBeenCalledWith("https://t.me/test", "_blank", "noopener,noreferrer");
    openSpy.mockRestore();
  });

  it("refuses non-t.me http(s) URLs", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    mod.openTelegramLink("https://example.com");
    expect(fake.openTelegramLink).not.toHaveBeenCalled();
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it.each([
    ["javascript:alert(1)"],
    ["JavaScript:alert(1)"],
    ["data:text/html,<script>alert(1)</script>"],
    ["vbscript:msgbox"],
    ["file:///etc/passwd"],
    ["not-a-url"],
    [""],
  ])("refuses to open unsafe URL %s", async (badUrl) => {
    // Audit L-13 — only ``http(s):`` URLs are allowed through. Anything
    // else is silently dropped before delegating to Telegram or to
    // ``window.open`` so a server-injected URL can't execute script.
    const { fake, mod } = await importTgWithFake("ios");
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    mod.openTelegramLink(badUrl);
    expect(fake.openTelegramLink).not.toHaveBeenCalled();
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });

  it("refuses unsafe URLs in the no-Telegram fallback too", async () => {
    (window as unknown as { Telegram?: unknown }).Telegram = undefined;
    vi.resetModules();
    const mod = await import("./tg");
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    mod.openTelegramLink("javascript:alert(1)");
    expect(openSpy).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });
});

describe("showBackButton / showMainButton", () => {
  it("showBackButton wires onClick + show and returns a teardown", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    const cb = () => {};
    const teardown = mod.showBackButton(cb);
    expect(fake.BackButton.onClick).toHaveBeenCalledWith(cb);
    expect(fake.BackButton.show).toHaveBeenCalled();
    teardown();
    expect(fake.BackButton.offClick).toHaveBeenCalledWith(cb);
    expect(fake.BackButton.hide).toHaveBeenCalled();
  });

  it("showBackButton returns a no-op teardown when Telegram is unavailable", async () => {
    (window as unknown as { Telegram?: unknown }).Telegram = undefined;
    vi.resetModules();
    const mod = await import("./tg");
    const teardown = mod.showBackButton(() => {});
    expect(() => teardown()).not.toThrow();
  });

  it("showMainButton configures + binds onClick and returns a teardown", async () => {
    const { fake, mod } = await importTgWithFake("ios");
    const cb = () => {};
    const teardown = mod.showMainButton("Submit", cb);
    expect(fake.MainButton.setParams).toHaveBeenCalledWith(
      expect.objectContaining({ text: "Submit", is_visible: true, is_active: true }),
    );
    expect(fake.MainButton.onClick).toHaveBeenCalledWith(cb);
    teardown();
    expect(fake.MainButton.offClick).toHaveBeenCalledWith(cb);
    expect(fake.MainButton.hide).toHaveBeenCalled();
  });
});
