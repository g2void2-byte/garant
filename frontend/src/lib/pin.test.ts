import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  PIN_TOKEN_CHANGED_EVENT,
  clearPinToken,
  getPinToken,
  hasValidPinToken,
  setPinToken,
} from "./pin";

describe("pin token storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.useRealTimers();
  });

  it("returns null when nothing is stored", () => {
    expect(getPinToken()).toBeNull();
    expect(hasValidPinToken()).toBe(false);
  });

  it("stores and reads back a non-expired token", () => {
    const future = new Date(Date.now() + 60_000).toISOString();
    setPinToken("tok-123", future);
    expect(getPinToken()).toBe("tok-123");
    expect(hasValidPinToken()).toBe(true);
  });

  it("clears the token via clearPinToken", () => {
    const future = new Date(Date.now() + 60_000).toISOString();
    setPinToken("tok-123", future);
    clearPinToken();
    expect(getPinToken()).toBeNull();
    expect(hasValidPinToken()).toBe(false);
  });

  it("auto-clears expired tokens on read", () => {
    const past = new Date(Date.now() - 1_000).toISOString();
    window.localStorage.setItem("garant.pin_token", "tok-expired");
    window.localStorage.setItem("garant.pin_token_expires", past);
    expect(getPinToken()).toBeNull();
    // The expired entry should also have been wiped from storage.
    expect(window.localStorage.getItem("garant.pin_token")).toBeNull();
  });

  it("auto-clears tokens with malformed stored expiry values", () => {
    window.localStorage.setItem("garant.pin_token", "tok-invalid-expiry");
    window.localStorage.setItem("garant.pin_token_expires", "not-a-date");
    expect(getPinToken()).toBeNull();
    expect(hasValidPinToken()).toBe(false);
    expect(window.localStorage.getItem("garant.pin_token")).toBeNull();
    expect(window.localStorage.getItem("garant.pin_token_expires")).toBeNull();
  });

  it("dispatches the change event on set and clear", () => {
    const listener = vi.fn();
    window.addEventListener(PIN_TOKEN_CHANGED_EVENT, listener);
    setPinToken("tok-evt", new Date(Date.now() + 60_000).toISOString());
    expect(listener).toHaveBeenCalledTimes(1);
    clearPinToken();
    expect(listener).toHaveBeenCalledTimes(2);
    window.removeEventListener(PIN_TOKEN_CHANGED_EVENT, listener);
  });
});
