import { QueryClient } from "@tanstack/react-query";
import type { HTTPError } from "ky";

// Shared QueryClient. Lives in its own module so non-React code (e.g.
// the ky 401 interceptor in `api/client.ts`) can invalidate cached
// queries without importing from `App.tsx`, which would create an
// import cycle.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      // Item 22 — pull a fresh snapshot whenever the TMA / browser tab
      // returns to the foreground. Telegram backgrounds the WebView
      // aggressively and the notifications WS may have missed a frame
      // while we were suspended; refetching on focus closes the
      // "swiped away → came back to a stale deal" gap that the WS
      // alone can't cover.
      refetchOnWindowFocus: true,
      // Bug-12 — never retry a 429. Pre-fix, ``retry: 1`` would
      // re-fire the very request that just got rate-limited, which
      // burned through the rate-limit window and kept the UI in a
      // perma-loading state. Other failures still get one retry to
      // tolerate transient blips.
      retry: (failureCount, error) => {
        const status = (error as HTTPError | undefined)?.response?.status;
        if (status === 429) return false;
        return failureCount < 1;
      },
    },
  },
});
