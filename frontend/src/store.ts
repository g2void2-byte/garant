import { create } from "zustand";
import type { User } from "./api";
import { api } from "./api";

interface State {
  user: User | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  setUser: (u: User) => void;
}

export const useUser = create<State>((set) => ({
  user: null,
  loading: false,
  error: null,
  refresh: async () => {
    set({ loading: true, error: null });
    try {
      const u = await api.me();
      set({ user: u, loading: false });
    } catch (e) {
      set({ error: (e as Error).message, loading: false });
    }
  },
  setUser: (u) => set({ user: u }),
}));
