import { afterEach, describe, expect, it, vi } from "vitest";
import { __testing, installDevtoolsGuard } from "./devtoolsGuard";

const { isBlockedKeydown } = __testing;

function ke(init: Partial<KeyboardEvent>): KeyboardEvent {
  return new KeyboardEvent("keydown", {
    key: "",
    ctrlKey: false,
    shiftKey: false,
    altKey: false,
    metaKey: false,
    ...init,
  });
}

describe("isBlockedKeydown", () => {
  it("blocks the devtools-opening keys", () => {
    expect(isBlockedKeydown(ke({ key: "F12" }))).toBe(true);
    expect(isBlockedKeydown(ke({ key: "F11" }))).toBe(true);
    expect(isBlockedKeydown(ke({ key: "I", ctrlKey: true, shiftKey: true }))).toBe(true);
    expect(isBlockedKeydown(ke({ key: "j", ctrlKey: true, shiftKey: true }))).toBe(true);
    expect(isBlockedKeydown(ke({ key: "C", ctrlKey: true, shiftKey: true }))).toBe(true);
    expect(isBlockedKeydown(ke({ key: "u", ctrlKey: true }))).toBe(true);
    expect(isBlockedKeydown(ke({ key: "s", ctrlKey: true }))).toBe(true);
    // metaKey alias for Mac.
    expect(isBlockedKeydown(ke({ key: "u", metaKey: true }))).toBe(true);
  });

  it("does not block ordinary typing or app shortcuts", () => {
    expect(isBlockedKeydown(ke({ key: "a" }))).toBe(false);
    expect(isBlockedKeydown(ke({ key: "Enter" }))).toBe(false);
    expect(isBlockedKeydown(ke({ key: "Tab" }))).toBe(false);
    // Ctrl+C / Ctrl+V / Ctrl+A must stay usable inside form inputs.
    expect(isBlockedKeydown(ke({ key: "c", ctrlKey: true }))).toBe(false);
    expect(isBlockedKeydown(ke({ key: "v", ctrlKey: true }))).toBe(false);
    expect(isBlockedKeydown(ke({ key: "a", ctrlKey: true }))).toBe(false);
    // Ctrl+I / Ctrl+J without Shift are not the devtools shortcut.
    expect(isBlockedKeydown(ke({ key: "i", ctrlKey: true }))).toBe(false);
    expect(isBlockedKeydown(ke({ key: "j", ctrlKey: true }))).toBe(false);
  });
});

describe("installDevtoolsGuard", () => {
  let cleanup: (() => void) | null = null;

  afterEach(() => {
    cleanup?.();
    cleanup = null;
  });

  it("preventDefaults blocked keydown events and right-click", () => {
    cleanup = installDevtoolsGuard();

    const keydown = new KeyboardEvent("keydown", { key: "F12", bubbles: true, cancelable: true });
    const prevented = !window.dispatchEvent(keydown);
    expect(prevented || keydown.defaultPrevented).toBe(true);

    const ctxMenu = new MouseEvent("contextmenu", { bubbles: true, cancelable: true });
    window.dispatchEvent(ctxMenu);
    expect(ctxMenu.defaultPrevented).toBe(true);
  });

  it("lets non-blocked keys through", () => {
    cleanup = installDevtoolsGuard();

    const keydown = new KeyboardEvent("keydown", { key: "a", bubbles: true, cancelable: true });
    window.dispatchEvent(keydown);
    expect(keydown.defaultPrevented).toBe(false);
  });

  it("cleanup removes the listeners", () => {
    const teardown = installDevtoolsGuard();
    teardown();
    cleanup = null;

    const keydown = new KeyboardEvent("keydown", { key: "F12", bubbles: true, cancelable: true });
    window.dispatchEvent(keydown);
    // After cleanup the guard should not preventDefault any more.
    expect(keydown.defaultPrevented).toBe(false);
  });

  it("is a no-op in SSR-style environments without window", () => {
    const originalWindow = globalThis.window;
    // @ts-expect-error \u2014 force-delete to simulate SSR.
    delete globalThis.window;
    try {
      const noop = installDevtoolsGuard();
      expect(typeof noop).toBe("function");
      expect(() => noop()).not.toThrow();
    } finally {
      // Restore so the rest of the suite still has a window.
      (globalThis as unknown as { window: typeof originalWindow }).window = originalWindow;
    }
    // Silence the spy import to keep eslint quiet about unused imports.
    void vi;
  });
});
