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

  it("setHideDesignations(true) writes '1' to localStorage", async () => {
    const { useUI } = await importUI();
    useUI.getState().setHideDesignations(true);
    expect(window.localStorage.getItem("hideDesignations")).toBe("1");
    expect(useUI.getState().hideDesignations).toBe(true);
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
