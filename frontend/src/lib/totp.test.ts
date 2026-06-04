import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  TOTP_TOKEN_CHANGED_EVENT,
  clearTotpSessionToken,
  getTotpSessionToken,
  hasValidTotpSessionToken,
  setTotpSessionToken,
} from "./totp";

describe("totp session token storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.useRealTimers();
  });

  it("returns null when nothing is stored", () => {
    expect(getTotpSessionToken()).toBeNull();
    expect(hasValidTotpSessionToken()).toBe(false);
  });

  it("stores and reads back a non-expired token", () => {
    const future = new Date(Date.now() + 60_000).toISOString();
    setTotpSessionToken("totp-123", future);
    expect(getTotpSessionToken()).toBe("totp-123");
    expect(hasValidTotpSessionToken()).toBe(true);
  });

  it("clears the token via clearTotpSessionToken", () => {
    const future = new Date(Date.now() + 60_000).toISOString();
    setTotpSessionToken("totp-123", future);
    clearTotpSessionToken();
    expect(getTotpSessionToken()).toBeNull();
    expect(hasValidTotpSessionToken()).toBe(false);
  });

  it("auto-clears expired tokens on read", () => {
    const past = new Date(Date.now() - 1_000).toISOString();
    window.localStorage.setItem("garant.totp_session_token", "totp-expired");
    window.localStorage.setItem("garant.totp_session_token_expires", past);
    expect(getTotpSessionToken()).toBeNull();
    expect(window.localStorage.getItem("garant.totp_session_token")).toBeNull();
  });

  it("auto-clears tokens with malformed stored expiry values", () => {
    window.localStorage.setItem("garant.totp_session_token", "totp-invalid-expiry");
    window.localStorage.setItem("garant.totp_session_token_expires", "not-a-date");
    expect(getTotpSessionToken()).toBeNull();
    expect(hasValidTotpSessionToken()).toBe(false);
    expect(window.localStorage.getItem("garant.totp_session_token")).toBeNull();
    expect(window.localStorage.getItem("garant.totp_session_token_expires")).toBeNull();
  });

  it("dispatches the change event on set and clear", () => {
    const listener = vi.fn();
    window.addEventListener(TOTP_TOKEN_CHANGED_EVENT, listener);
    setTotpSessionToken("totp-evt", new Date(Date.now() + 60_000).toISOString());
    expect(listener).toHaveBeenCalledTimes(1);
    clearTotpSessionToken();
    expect(listener).toHaveBeenCalledTimes(2);
    window.removeEventListener(TOTP_TOKEN_CHANGED_EVENT, listener);
  });
});
