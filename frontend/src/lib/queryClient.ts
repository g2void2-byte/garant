import { QueryClient } from "@tanstack/react-query";

// Shared QueryClient. Lives in its own module so non-React code (e.g.
// the ky 401 interceptor in `api/client.ts`) can invalidate cached
// queries without importing from `App.tsx`, which would create an
// import cycle.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});
