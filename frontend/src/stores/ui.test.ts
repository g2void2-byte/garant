import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The zustand store reads from ``localStorage`` at module evaluation
 * time, so each scenario has to seed storage *before* importing the
 * module. ``vi.resetModules()`` + dynamic ``import("./ui")`` is the
 * canonical way to do this without polluting the cache between tests.
 */
async function importUI() {
  vi.resetModules();
  const mod = await import("./ui");
  return mod;
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("useUI store", () => {
  it("defaults searchMode to 'users'", async () => {
    const { useUI } = await importUI();
    expect(useUI.getState().searchMode).toBe("users");
  });

  it("setSearchMode updates the mode", async () => {
    const { useUI } = await importUI();
    useUI.getState().setSearchMode("services");
    expect(useUI.getState().searchMode).toBe("services");
    useUI.getState().setSearchMode("users");
    expect(useUI.getState().searchMode).toBe("users");
  });

  it("defaults hideDesignations to false when localStorage is empty", async () => {
    const { useUI } = await importUI();
    expect(useUI.getState().hideDesignations).toBe(false);
  });

  it("reads hideDesignations=true from localStorage on init", async () => {
    window.localStorage.setItem("hideDesignations", "1");
    const { useUI } = await importUI();
    expect(useUI.getState().hideDesignations).toBe(true);
  });

  it("does not throw on import when localStorage reads are blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const { useUI } = await importUI();
    expect(useUI.getState().hideDesignations).toBe(false);
  });

  it("setHideDesignations(true) writes '1' to localStorage", async () => {
    const { useUI } = await importUI();
    useUI.getState().setHideDesignations(true);
    expect(window.localStorage.getItem("hideDesignations")).toBe("1");
    expect(useUI.getState().hideDesignations).toBe(true);
  });

  it("updates in-memory state when localStorage writes are blocked", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    const { useUI } = await importUI();
    useUI.getState().setHideDesignations(true);
    expect(useUI.getState().hideDesignations).toBe(true);
    useUI.getState().setHideDesignations(false);
    expect(useUI.getState().hideDesignations).toBe(false);
  });

  it("setHideDesignations(false) removes the key from localStorage", async () => {
    window.localStorage.setItem("hideDesignations", "1");
    const { useUI } = await importUI();
    expect(useUI.getState().hideDesignations).toBe(true);
    useUI.getState().setHideDesignations(false);
    expect(window.localStorage.getItem("hideDesignations")).toBeNull();
    expect(useUI.getState().hideDesignations).toBe(false);
  });
});
