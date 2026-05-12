import { create } from "zustand";

interface UIState {
  searchMode: "users" | "services";
  setSearchMode: (mode: "users" | "services") => void;
  hideDesignations: boolean;
  setHideDesignations: (v: boolean) => void;
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
}));
