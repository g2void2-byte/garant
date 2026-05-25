import { create } from "zustand";

interface UIState {
  searchMode: "users" | "services";
  setSearchMode: (mode: "users" | "services") => void;
  hideDesignations: boolean;
  setHideDesignations: (v: boolean) => void;
  // Global open/close flag for the slide-in admin menu drawer.
  // Hoisted to ``useUI`` (rather than living on each admin page)
  // so the menu button rendered on /admin/* headers can toggle the
  // drawer regardless of which page mounted it.
  adminMenuOpen: boolean;
  setAdminMenuOpen: (v: boolean) => void;
  toggleAdminMenu: () => void;
}

export const useUI = create<UIState>((set) => ({
  searchMode: "users",
  setSearchMode: (mode) => set({ searchMode: mode }),
  hideDesignations: typeof window !== "undefined" && window.localStorage.getItem("hideDesignations") === "1",
  setHideDesignations: (v) => {
    if (typeof window !== "undefined") {
      if (v) window.localStorage.setItem("hideDesignations", "1");
      else window.localStorage.removeItem("hideDesignations");
    }
    set({ hideDesignations: v });
  },
  adminMenuOpen: false,
  setAdminMenuOpen: (v) => set({ adminMenuOpen: v }),
  toggleAdminMenu: () => set((s) => ({ adminMenuOpen: !s.adminMenuOpen })),
}));
