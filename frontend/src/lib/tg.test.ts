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
