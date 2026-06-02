/**
 * A-7 — Typed query-key factory.
 *
 * Centralises every TanStack-Query key the app uses so that:
 *
 *   1. Typos are compile-time errors instead of silent cache misses.
 *      Pre-refactor every callsite passed a string-tuple literal;
 *      `qc.invalidateQueries({queryKey: ["delas"]})` typo'd "deals"
 *      and silently invalidated nothing.
 *
 *   2. Each tuple is a literal (``as const``) so IDEs can autocomplete
 *      the namespace path and ``getQueryData`` / ``setQueryData``
 *      callers get the narrow tuple type back.
 *
 *   3. There is exactly one place to look when you want to know what
 *      cached entries exist under a given prefix. Pre-refactor that
 *      knowledge was scattered across ~50 call sites in
 *      ``frontend/src/api/hooks.ts`` + ``frontend/src/api/admin/hooks.ts``.
 *
 * Every namespace follows the same shape:
 *
 *   - ``all()`` returns the prefix tuple. Use it with
 *     ``qc.invalidateQueries({queryKey: qk.deal.all()})`` — TanStack
 *     Query treats a partial key as a prefix and matches every cached
 *     entry whose key starts with the same elements.
 *
 *   - Leaf accessors (``detail(id)``, ``list(params)``, etc.) return
 *     the full tuple. Use them with ``useQuery({queryKey: qk.deal.detail(id)})``
 *     so the cache is keyed exactly the same way every time and no
 *     two callers diverge on parameter shape.
 *
 * Adding a new namespace: keep the tuple shape identical to whatever
 * the corresponding ``useQuery`` callsite would have used before this
 * refactor — that way migrations are mechanical and cache hits are
 * preserved across the deploy.
 */

import type {
  AdminListDealsQuery,
  AdminListUsersQuery,
} from "./types";

// Local param shapes for namespaces whose query types aren't exported
// from ``types.ts``. Keep these structural so callers don't need to
// import anything extra — the factory takes whatever the existing
// hook took before this refactor.
export interface AdminDepositsQueryKey {
  status?: string;
  currency?: string;
  q?: string;
  page?: number;
  page_size?: number;
}

export interface AdminWalletsQueryKey {
  q?: string;
  page?: number;
  page_size?: number;
}

export interface AdminWithdrawalsQueryKey {
  status?: string;
  q?: string;
  page?: number;
}

export interface AdminAuditQueryKey {
  action?: string;
  actor_id?: number;
  target_type?: string;
  target_id?: number;
  page?: number;
  page_size?: number;
}

export interface AdminUserContentQueryKey {
  page?: number;
  page_size?: number;
}

export interface ServicesQueryKey {
  category?: string;
  q?: string;
  owner?: string;
  status?: string;
}

export interface UsersQueryKey {
  q?: string;
  filter?: string;
  rating?: string;
  deals?: string;
  status?: string;
  reg_from?: string;
  reg_to?: string;
}

export interface DealsQueryKey {
  role?: string;
  status?: string;
}

export const qk = {
  // ── Public / user-facing ─────────────────────────────────────
  me: () => ["me"] as const,
  categories: () => ["categories"] as const,
  maintenance: () => ["maintenance"] as const,
  publicSettings: () => ["public-settings"] as const,
  publicStats: () => ["public-stats"] as const,
  // Audit v3 A-1 — public list of approved forum names. The
  // backend is the single source of truth; the AddForumPage
  // dropdown fetches this list so the frontend cannot drift from
  // ``FORUM_WHITELIST``.
  forums: () => ["forums"] as const,
  // H-1 — ``invoiceStatus`` retired alongside the legacy
  // ``GET /api/payments/deposit/invoice/{id}`` polling fallback.
  // Wallet deposits are tracked under ``qk.wallet.deposit(id)``.

  services: {
    all: () => ["services"] as const,
    list: (params: ServicesQueryKey) => ["services", params] as const,
  },
  service: {
    all: () => ["service"] as const,
    detail: (id: number | undefined) => ["service", id] as const,
    comments: (id: number | undefined) =>
      ["service", id, "comments"] as const,
  },
  users: {
    all: () => ["users"] as const,
    list: (params: UsersQueryKey) => ["users", params] as const,
  },
  user: {
    all: () => ["user"] as const,
    detail: (username: string | undefined) => ["user", username] as const,
  },
  deals: {
    all: () => ["deals"] as const,
    list: (params: DealsQueryKey) => ["deals", params] as const,
  },
  deal: {
    all: () => ["deal"] as const,
    detail: (id: number | undefined) => ["deal", id] as const,
    messages: (id: number | undefined) =>
      ["deal", id, "messages"] as const,
  },
  reviews: {
    all: () => ["reviews"] as const,
    forUser: (username: string | undefined) =>
      ["reviews", username] as const,
  },
  notifications: {
    all: () => ["notifications"] as const,
    // ``type ?? "all"`` mirrors the original useNotifications hook so
    // a caller that omits the filter still hits the same cache slot.
    list: (type: string | undefined) =>
      ["notifications", type ?? "all"] as const,
    detail: (id: number | undefined) =>
      ["notifications", "detail", id] as const,
    counters: () => ["notifications", "counters"] as const,
  },
  support: {
    admins: () => ["support", "admins"] as const,
    arbiters: () => ["support", "arbiters"] as const,
  },
  // H-1 — ``qk.payments`` retired alongside the legacy ``Invoice``
  // ledger and its ``/api/payments/deposit*`` endpoints. The
  // multi-currency wallet equivalent is ``qk.wallet`` below.
  pin: {
    all: () => ["pin"] as const,
    status: () => ["pin", "status"] as const,
  },
  account: {
    transfer: {
      all: () => ["account", "transfer"] as const,
      status: () => ["account", "transfer", "status"] as const,
    },
  },
  wallet: {
    all: () => ["wallet"] as const,
    currencies: () => ["wallet", "currencies"] as const,
    // Item 15 — separate cache slot per kind filter so a
    // ``?kind=fiat`` and a no-filter call don't clobber each other.
    currenciesByKind: (kind: "fiat" | "crypto") =>
      ["wallet", "currencies", kind] as const,
    balances: () => ["wallet", "balances"] as const,
    balancesByKind: (kind: "fiat" | "crypto") =>
      ["wallet", "balances", kind] as const,
    deposits: () => ["wallet", "deposits"] as const,
    deposit: (id: number | undefined) =>
      ["wallet", "deposit", id] as const,
    withdrawals: () => ["wallet", "withdrawals"] as const,
  },
  arbitration: {
    deals: () => ["arbitration", "deals"] as const,
  },

  // ── Admin ────────────────────────────────────────────────────
  admin: {
    dashboard: () => ["admin", "dashboard"] as const,

    users: {
      all: () => ["admin", "users"] as const,
      list: (params: AdminListUsersQuery) =>
        ["admin", "users", params] as const,
    },
    user: {
      all: () => ["admin", "user"] as const,
      detail: (id: number | undefined) =>
        ["admin", "user", id] as const,
    },
    userServices: {
      all: () => ["admin", "user-services"] as const,
      forUser: (id: number | undefined) =>
        ["admin", "user-services", id] as const,
      list: (id: number | undefined, params: AdminUserContentQueryKey) =>
        ["admin", "user-services", id, params] as const,
    },
    userReviews: {
      all: () => ["admin", "user-reviews"] as const,
      forUser: (id: number | undefined) =>
        ["admin", "user-reviews", id] as const,
      forUserDirection: (id: number | undefined, direction: string) =>
        ["admin", "user-reviews", id, direction] as const,
      list: (
        id: number | undefined,
        direction: string,
        params: AdminUserContentQueryKey,
      ) => ["admin", "user-reviews", id, direction, params] as const,
    },
    userComments: {
      all: () => ["admin", "user-comments"] as const,
      forUser: (id: number | undefined) =>
        ["admin", "user-comments", id] as const,
      list: (id: number | undefined, params: AdminUserContentQueryKey) =>
        ["admin", "user-comments", id, params] as const,
    },
    userWallet: {
      all: () => ["admin", "user-wallet"] as const,
      forUser: (id: number | undefined) =>
        ["admin", "user-wallet", id] as const,
    },

    deals: {
      all: () => ["admin", "deals"] as const,
      list: (params: AdminListDealsQuery) =>
        ["admin", "deals", params] as const,
    },
    deal: {
      all: () => ["admin", "deal"] as const,
      detail: (id: number | undefined) =>
        ["admin", "deal", id] as const,
    },

    arbitration: {
      all: () => ["admin", "arbitration"] as const,
      queue: (queue: string, page: number, pageSize: number) =>
        ["admin", "arbitration", queue, page, pageSize] as const,
    },

    wallets: {
      all: () => ["admin", "wallets"] as const,
      list: (params: AdminWalletsQueryKey) =>
        ["admin", "wallets", params] as const,
    },

    deposits: {
      all: () => ["admin", "deposits"] as const,
      list: (params: AdminDepositsQueryKey) =>
        ["admin", "deposits", params] as const,
    },

    withdrawals: {
      all: () => ["admin", "withdrawals"] as const,
      list: (params: AdminWithdrawalsQueryKey) =>
        ["admin", "withdrawals", params] as const,
    },


    settings: () => ["admin", "settings"] as const,
    categories: () => ["admin", "categories"] as const,
    currencies: () => ["admin", "currencies"] as const,
    broadcasts: () => ["admin", "broadcasts"] as const,

    analytics: {
      kpi: () => ["admin", "analytics-kpi"] as const,
      series: () => ["admin", "analytics-series"] as const,
      top: () => ["admin", "analytics-top"] as const,
    },

    systemStatus: () => ["admin", "system-status"] as const,

    twoFa: {
      status: () => ["admin", "2fa-status"] as const,
    },

    audit: {
      all: () => ["admin", "audit"] as const,
      list: (params: AdminAuditQueryKey) =>
        ["admin", "audit", params] as const,
    },
  },
} as const;
