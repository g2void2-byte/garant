/**
 * TanStack Query hooks for the admin panel.
 *
 * Every mutation that changes a user's state invalidates BOTH the list
 * (`["admin", "users", ...]`) and the detail (`["admin", "user", id]`)
 * so the UI stays consistent without manually patching the cache.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import type {
  Admin2faConfirmBody,
  Admin2faSetupDto,
  Admin2faStatusDto,
  Admin2faVerifyBody,
  AdminAnalyticsKpiDto,
  AdminAnalyticsSeriesDto,
  AdminAnalyticsTopListsDto,
  AdminArbitrationListDto,
  AdminAuditLogListDto,
  AdminBroadcastCreateBody,
  AdminBroadcastDto,
  AdminBroadcastListDto,
  AdminBroadcastPreviewDto,
  AdminCategoryDto,
  AdminCategoryUpsertBody,
  AdminCommentItemDto,
  AdminCommentUpdateBody,
  AdminCurrencyDto,
  AdminCurrencyUpsertBody,
  AdminDashboardDto,
  AdminDealDetailDto,
  AdminDealListDto,
  AdminDepositDto,
  AdminDepositListDto,
  AdminListDealsQuery,
  AdminListUsersQuery,
  AdminReviewItemDto,
  AdminReviewUpsertBody,
  AdminServiceItemDto,
  AdminServiceUpdateBody,
  AdminSettingsDto,
  AdminSettingsUpdateBody,
  AdminSystemStatusDto,
  AdminTreasuryOverviewDto,
  AdminTreasuryWithdrawBody,
  AdminTreasuryWithdrawDto,
  AdminUserBalanceDto,
  AdminUserDetailDto,
  AdminUserListDto,
  AdminWalletAdjustBody,
  AdminWalletListDto,
  AdminWithdrawalDecisionBody,
  AdminWithdrawalDto,
  AdminWithdrawalListDto,
} from "../types";

// ── Dashboard ────────────────────────────────────────────────────────────

export function useAdminDashboard() {
  return useQuery<AdminDashboardDto>({
    queryKey: ["admin", "dashboard"],
    queryFn: () => api.get("api/admin/dashboard").json(),
    refetchInterval: 30_000,
  });
}

// ── Users — list / detail ────────────────────────────────────────────────

function buildUsersSearchParams(query: AdminListUsersQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.role && query.role !== "any") params.set("role", query.role);
  if (query.status && query.status !== "any") params.set("status", query.status);
  if (query.sort) params.set("sort", query.sort);
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.page_size ?? 20));
  return params;
}

export function useAdminUsers(query: AdminListUsersQuery) {
  return useQuery<AdminUserListDto>({
    queryKey: ["admin", "users", query],
    queryFn: () =>
      api
        .get("api/admin/users", { searchParams: buildUsersSearchParams(query) })
        .json(),
    placeholderData: (prev) => prev,
  });
}

export function useAdminUser(userId: number | undefined) {
  return useQuery<AdminUserDetailDto>({
    queryKey: ["admin", "user", userId],
    queryFn: () => api.get(`api/admin/users/${userId}`).json(),
    enabled: typeof userId === "number" && Number.isFinite(userId),
  });
}

// ── Generic action helper ────────────────────────────────────────────────

interface AdminActionArgs {
  userId: number;
  body?: Record<string, unknown>;
}

function useAdminUserAction(action: string) {
  const qc = useQueryClient();
  return useMutation<AdminUserDetailDto, Error, AdminActionArgs>({
    mutationFn: ({ userId, body }) =>
      api
        .post(`api/admin/users/${userId}/${action}`, {
          json: body ?? {},
        })
        .json(),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      qc.invalidateQueries({ queryKey: ["admin", "user", vars.userId] });
      qc.invalidateQueries({ queryKey: ["admin", "dashboard"] });
    },
  });
}

export function useAdminBanUser() {
  return useAdminUserAction("ban");
}

export function useAdminUnbanUser() {
  return useAdminUserAction("unban");
}

export function useAdminFreezeUser() {
  return useAdminUserAction("freeze");
}

export function useAdminUnfreezeUser() {
  return useAdminUserAction("unfreeze");
}

export function useAdminResetPin() {
  return useAdminUserAction("reset-pin");
}

export function useAdminInvalidateSessions() {
  return useAdminUserAction("invalidate-sessions");
}

export function useAdminSetRole() {
  return useAdminUserAction("role");
}

export function useAdminSetRating() {
  return useAdminUserAction("rating");
}

export function useAdminSetStats() {
  return useAdminUserAction("stats");
}

// ── Deals — list / detail / actions (PR-B) ──────────────────────────────

function buildDealsSearchParams(query: AdminListDealsQuery): URLSearchParams {
  const params = new URLSearchParams();
  if (query.status && query.status !== "any") params.set("status", query.status);
  if (query.currency) params.set("currency", query.currency);
  if (query.min_sum !== undefined) params.set("min_sum", String(query.min_sum));
  if (query.max_sum !== undefined) params.set("max_sum", String(query.max_sum));
  if (query.has_arbitration) params.set("has_arbitration", "true");
  if (query.has_cancel_request) params.set("has_cancel_request", "true");
  if (query.buyer_id !== undefined) params.set("buyer_id", String(query.buyer_id));
  if (query.seller_id !== undefined) params.set("seller_id", String(query.seller_id));
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.page_size ?? 20));
  return params;
}

export function useAdminDeals(query: AdminListDealsQuery) {
  return useQuery<AdminDealListDto>({
    queryKey: ["admin", "deals", query],
    queryFn: () =>
      api.get("api/admin/deals", { searchParams: buildDealsSearchParams(query) }).json(),
    placeholderData: (prev) => prev,
  });
}

export function useAdminDeal(dealId: number | undefined) {
  return useQuery<AdminDealDetailDto>({
    queryKey: ["admin", "deal", dealId],
    queryFn: () => api.get(`api/admin/deals/${dealId}`).json(),
    enabled: typeof dealId === "number" && Number.isFinite(dealId),
  });
}

interface DealActionVars {
  dealId: number;
  body?: Record<string, unknown>;
}

function useAdminDealAction(action: string) {
  const qc = useQueryClient();
  return useMutation<AdminDealDetailDto | { deleted?: boolean }, Error, DealActionVars>({
    mutationFn: async ({ dealId, body }) => {
      const json = await api
        .post(`api/admin/deals/${dealId}/${action}`, { json: body ?? {} })
        .json<{ deal?: AdminDealDetailDto; deleted?: boolean }>();
      return json.deal ?? json;
    },
    onSuccess: (data, vars) => {
      qc.invalidateQueries({ queryKey: ["admin", "deals"] });
      qc.invalidateQueries({ queryKey: ["admin", "deal", vars.dealId] });
      qc.invalidateQueries({ queryKey: ["admin", "arbitration"] });
      qc.invalidateQueries({ queryKey: ["admin", "dashboard"] });
      // V5-F-5: when the response carries the full AdminDealDetailDto,
      // also invalidate the buyer + seller user-detail queries so an
      // admin viewing one of the parties sees the post-action balance.
      // The other branch of the union is `{ deleted?: boolean }`, which
      // has no party ids and is intentionally skipped.
      if (
        data &&
        typeof data === "object" &&
        "buyer" in data &&
        "seller" in data
      ) {
        qc.invalidateQueries({ queryKey: ["admin", "user", data.buyer.user_id] });
        qc.invalidateQueries({ queryKey: ["admin", "user", data.seller.user_id] });
      }
    },
  });
}

export function useAdminForceRelease() {
  return useAdminDealAction("force-release");
}
export function useAdminForceRefund() {
  return useAdminDealAction("force-refund");
}
export function useAdminSplitDeal() {
  return useAdminDealAction("split");
}
export function useAdminForceArbitration() {
  return useAdminDealAction("force-arbitration");
}
export function useAdminAssignArbiter() {
  return useAdminDealAction("assign-arbiter");
}
export function useAdminDeleteDeal() {
  return useAdminDealAction("delete");
}

// ── Arbitration queue (PR-B) ─────────────────────────────────────────────

export function useAdminArbitration(
  queue: "new" | "in_progress" | "closed",
  page = 1,
  page_size = 20,
) {
  return useQuery<AdminArbitrationListDto>({
    queryKey: ["admin", "arbitration", queue, page, page_size],
    queryFn: () => {
      const params = new URLSearchParams({
        queue,
        page: String(page),
        page_size: String(page_size),
      });
      return api.get("api/admin/arbitration", { searchParams: params }).json();
    },
    placeholderData: (prev) => prev,
  });
}

export function useAdminClaimArbitration() {
  const qc = useQueryClient();
  return useMutation<{ claimed: boolean; deal_id: number; arbiter_id: number }, Error, number>({
    mutationFn: (dealId) =>
      api.post(`api/admin/arbitration/${dealId}/claim`).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "arbitration"] });
      qc.invalidateQueries({ queryKey: ["admin", "deals"] });
      // V5-F-5: claim response only carries `{ claimed, deal_id, arbiter_id }`
      // and does NOT expose buyer/seller ids. Fall back to a prefix-only
      // invalidation — TanStack Query treats `["admin", "user"]` as a
      // prefix and matches every cached `["admin", "user", N]` query.
      qc.invalidateQueries({ queryKey: ["admin", "user"] });
    },
  });
}

// ── Services / Reviews / Comments (PR-B) ─────────────────────────────────

export function useAdminUserServices(userId: number | undefined) {
  return useQuery<AdminServiceItemDto[]>({
    queryKey: ["admin", "user-services", userId],
    queryFn: () => api.get(`api/admin/users/${userId}/services`).json(),
    enabled: typeof userId === "number" && Number.isFinite(userId),
  });
}

export function useAdminUpdateService(userId?: number) {
  const qc = useQueryClient();
  return useMutation<
    AdminServiceItemDto,
    Error,
    { serviceId: number; body: AdminServiceUpdateBody }
  >({
    mutationFn: ({ serviceId, body }) =>
      api.post(`api/admin/services/${serviceId}`, { json: body }).json(),
    onSuccess: () => {
      if (userId !== undefined) {
        qc.invalidateQueries({ queryKey: ["admin", "user-services", userId] });
      }
      qc.invalidateQueries({ queryKey: ["admin", "user", userId] });
    },
  });
}

export function useAdminDeleteService(userId?: number) {
  const qc = useQueryClient();
  return useMutation<{ deleted: true }, Error, number>({
    mutationFn: (serviceId) =>
      api.post(`api/admin/services/${serviceId}/delete`).json(),
    onSuccess: () => {
      if (userId !== undefined) {
        qc.invalidateQueries({ queryKey: ["admin", "user-services", userId] });
      }
    },
  });
}

export function useAdminUserReviews(userId: number | undefined, direction: "received" | "written" = "received") {
  return useQuery<AdminReviewItemDto[]>({
    queryKey: ["admin", "user-reviews", userId, direction],
    queryFn: () =>
      api
        .get(`api/admin/users/${userId}/reviews`, {
          searchParams: { direction },
        })
        .json(),
    enabled: typeof userId === "number" && Number.isFinite(userId),
  });
}

export function useAdminCreateReview(userId?: number) {
  const qc = useQueryClient();
  return useMutation<AdminReviewItemDto, Error, AdminReviewUpsertBody>({
    mutationFn: (body) => api.post("api/admin/reviews", { json: body }).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "user-reviews", userId] });
    },
  });
}

export function useAdminUpdateReview(userId?: number) {
  const qc = useQueryClient();
  return useMutation<
    AdminReviewItemDto,
    Error,
    { reviewId: number; body: AdminReviewUpsertBody }
  >({
    mutationFn: ({ reviewId, body }) =>
      api.post(`api/admin/reviews/${reviewId}`, { json: body }).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "user-reviews", userId] });
    },
  });
}

export function useAdminDeleteReview(userId?: number) {
  const qc = useQueryClient();
  return useMutation<{ deleted: true }, Error, number>({
    mutationFn: (reviewId) =>
      api.post(`api/admin/reviews/${reviewId}/delete`).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "user-reviews", userId] });
    },
  });
}

export function useAdminUserComments(userId: number | undefined) {
  return useQuery<AdminCommentItemDto[]>({
    queryKey: ["admin", "user-comments", userId],
    queryFn: () => api.get(`api/admin/users/${userId}/comments`).json(),
    enabled: typeof userId === "number" && Number.isFinite(userId),
  });
}

export function useAdminUpdateComment(userId?: number) {
  const qc = useQueryClient();
  return useMutation<
    AdminCommentItemDto,
    Error,
    { commentId: number; body: AdminCommentUpdateBody }
  >({
    mutationFn: ({ commentId, body }) =>
      api.post(`api/admin/comments/${commentId}`, { json: body }).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "user-comments", userId] });
    },
  });
}

export function useAdminDeleteComment(userId?: number) {
  const qc = useQueryClient();
  return useMutation<{ deleted: true }, Error, number>({
    mutationFn: (commentId) =>
      api.post(`api/admin/comments/${commentId}/delete`).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "user-comments", userId] });
    },
  });
}

// ── PR-CDE: Wallets ─────────────────────────────────────────────────────

export function useAdminWallets(params: { q?: string; page?: number; page_size?: number }) {
  return useQuery<AdminWalletListDto>({
    queryKey: ["admin", "wallets", params],
    queryFn: () => {
      const sp = new URLSearchParams();
      if (params.q) sp.set("q", params.q);
      sp.set("page", String(params.page ?? 1));
      sp.set("page_size", String(params.page_size ?? 50));
      return api.get("api/admin/wallets", { searchParams: sp }).json();
    },
    placeholderData: (prev) => prev,
  });
}

export function useAdminUserWallet(userId: number | undefined) {
  return useQuery<AdminUserBalanceDto[]>({
    queryKey: ["admin", "user-wallet", userId],
    queryFn: () => api.get(`api/admin/wallets/${userId}`).json(),
    enabled: typeof userId === "number" && Number.isFinite(userId),
  });
}

export function useAdminAdjustBalance(userId: number) {
  const qc = useQueryClient();
  return useMutation<AdminUserBalanceDto, Error, AdminWalletAdjustBody>({
    mutationFn: (body) =>
      api.post(`api/admin/wallets/${userId}/adjust`, { json: body }).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "wallets"] });
      qc.invalidateQueries({ queryKey: ["admin", "user-wallet", userId] });
      qc.invalidateQueries({ queryKey: ["admin", "treasury"] });
    },
  });
}

// ── Deposits ────────────────────────────────────────────────────────────

export function useAdminDeposits(params: {
  status?: string;
  currency?: string;
  q?: string;
  page?: number;
  page_size?: number;
}) {
  return useQuery<AdminDepositListDto>({
    queryKey: ["admin", "deposits", params],
    queryFn: () => {
      const sp = new URLSearchParams();
      if (params.status) sp.set("status", params.status);
      if (params.currency) sp.set("currency", params.currency);
      if (params.q) sp.set("q", params.q);
      sp.set("page", String(params.page ?? 1));
      sp.set("page_size", String(params.page_size ?? 50));
      return api.get("api/admin/deposits", { searchParams: sp }).json();
    },
    placeholderData: (prev) => prev,
  });
}

export function useAdminDepositMarkPaid() {
  const qc = useQueryClient();
  return useMutation<AdminDepositDto, Error, { id: number; reason?: string }>({
    mutationFn: ({ id, reason }) =>
      api.post(`api/admin/deposits/${id}/mark-paid`, { json: { reason } }).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "deposits"] }),
  });
}

export function useAdminDepositRefund() {
  const qc = useQueryClient();
  return useMutation<AdminDepositDto, Error, { id: number; reason?: string }>({
    mutationFn: ({ id, reason }) =>
      api.post(`api/admin/deposits/${id}/refund`, { json: { reason } }).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "deposits"] }),
  });
}

// ── Withdrawals ─────────────────────────────────────────────────────────

export function useAdminWithdrawals(params: { status?: string; q?: string; page?: number }) {
  return useQuery<AdminWithdrawalListDto>({
    queryKey: ["admin", "withdrawals", params],
    queryFn: () => {
      const sp = new URLSearchParams();
      if (params.status) sp.set("status", params.status);
      if (params.q) sp.set("q", params.q);
      sp.set("page", String(params.page ?? 1));
      return api.get("api/admin/withdrawals", { searchParams: sp }).json();
    },
    placeholderData: (prev) => prev,
  });
}

export function useAdminDecideWithdrawal() {
  const qc = useQueryClient();
  return useMutation<AdminWithdrawalDto, Error, { id: number; body: AdminWithdrawalDecisionBody }>({
    mutationFn: ({ id, body }) =>
      api.post(`api/admin/withdrawals/${id}/decide`, { json: body }).json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "withdrawals"] });
      qc.invalidateQueries({ queryKey: ["admin", "wallets"] });
    },
  });
}

// ── Treasury ─────────────────────────────────────────────────────────────

export function useAdminTreasury() {
  return useQuery<AdminTreasuryOverviewDto>({
    queryKey: ["admin", "treasury"],
    queryFn: () => api.get("api/admin/treasury").json(),
  });
}

export function useAdminTreasuryWithdrawals() {
  return useQuery<AdminTreasuryWithdrawDto[]>({
    queryKey: ["admin", "treasury-history"],
    queryFn: () => api.get("api/admin/treasury/withdrawals").json(),
  });
}

export function useAdminTreasuryWithdraw() {
  const qc = useQueryClient();
  return useMutation<AdminTreasuryWithdrawDto, Error, { body: AdminTreasuryWithdrawBody; totpCode: string }>({
    mutationFn: ({ body, totpCode }) =>
      api
        .post("api/admin/treasury/withdraw", {
          json: body,
          headers: { "X-Totp-Code": totpCode },
        })
        .json(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin", "treasury"] });
      qc.invalidateQueries({ queryKey: ["admin", "treasury-history"] });
    },
  });
}

// ── Settings ────────────────────────────────────────────────────────────

export function useAdminSettings() {
  return useQuery<AdminSettingsDto>({
    queryKey: ["admin", "settings"],
    queryFn: () => api.get("api/admin/settings").json(),
  });
}

export function useAdminUpdateSettings() {
  const qc = useQueryClient();
  return useMutation<AdminSettingsDto, Error, AdminSettingsUpdateBody>({
    mutationFn: (body) => api.patch("api/admin/settings", { json: body }).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "settings"] }),
  });
}

// ── Taxonomy ────────────────────────────────────────────────────────────

export function useAdminCategories() {
  return useQuery<AdminCategoryDto[]>({
    queryKey: ["admin", "categories"],
    queryFn: () => api.get("api/admin/categories").json(),
  });
}

export function useAdminUpsertCategory() {
  const qc = useQueryClient();
  return useMutation<AdminCategoryDto, Error, AdminCategoryUpsertBody>({
    mutationFn: (body) => api.put("api/admin/categories", { json: body }).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "categories"] }),
  });
}

export function useAdminDeleteCategory() {
  const qc = useQueryClient();
  return useMutation<{ ok: boolean }, Error, number>({
    mutationFn: (id) => api.delete(`api/admin/categories/${id}`).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "categories"] }),
  });
}

export function useAdminCurrencies() {
  return useQuery<AdminCurrencyDto[]>({
    queryKey: ["admin", "currencies"],
    queryFn: () => api.get("api/admin/currencies").json(),
  });
}

export function useAdminUpsertCurrency() {
  const qc = useQueryClient();
  return useMutation<AdminCurrencyDto, Error, AdminCurrencyUpsertBody>({
    mutationFn: (body) => api.put("api/admin/currencies", { json: body }).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "currencies"] }),
  });
}

// ── Broadcasts ──────────────────────────────────────────────────────────

export function useAdminBroadcasts() {
  return useQuery<AdminBroadcastListDto>({
    queryKey: ["admin", "broadcasts"],
    queryFn: () => api.get("api/admin/broadcasts").json(),
  });
}

export function useAdminBroadcastPreview() {
  return useMutation<AdminBroadcastPreviewDto, Error, AdminBroadcastCreateBody>({
    mutationFn: (body) =>
      api.post("api/admin/broadcasts/preview", { json: body }).json(),
  });
}

export function useAdminCreateBroadcast() {
  const qc = useQueryClient();
  return useMutation<AdminBroadcastDto, Error, AdminBroadcastCreateBody>({
    mutationFn: (body) => api.post("api/admin/broadcasts", { json: body }).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "broadcasts"] }),
  });
}

export function useAdminDeleteBroadcast() {
  const qc = useQueryClient();
  return useMutation<{ ok: boolean }, Error, number>({
    mutationFn: (id) => api.delete(`api/admin/broadcasts/${id}`).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "broadcasts"] }),
  });
}

// ── Analytics ───────────────────────────────────────────────────────────

export function useAdminAnalyticsKpi() {
  return useQuery<AdminAnalyticsKpiDto>({
    queryKey: ["admin", "analytics-kpi"],
    queryFn: () => api.get("api/admin/analytics/kpi").json(),
    refetchInterval: 60_000,
  });
}

export function useAdminAnalyticsSeries() {
  return useQuery<AdminAnalyticsSeriesDto>({
    queryKey: ["admin", "analytics-series"],
    queryFn: () => api.get("api/admin/analytics/series").json(),
  });
}

export function useAdminAnalyticsTop() {
  return useQuery<AdminAnalyticsTopListsDto>({
    queryKey: ["admin", "analytics-top"],
    queryFn: () => api.get("api/admin/analytics/top").json(),
  });
}

// ── System ──────────────────────────────────────────────────────────────

export function useAdminSystemStatus() {
  return useQuery<AdminSystemStatusDto>({
    queryKey: ["admin", "system-status"],
    queryFn: () => api.get("api/admin/system/status").json(),
    refetchInterval: 10_000,
  });
}

export function useAdminFlushRedis() {
  return useMutation<{ ok: boolean; message?: string }, Error, void>({
    mutationFn: () => api.post("api/admin/system/redis/flush").json(),
  });
}

// ── 2FA ─────────────────────────────────────────────────────────────────

export function useAdmin2faStatus() {
  return useQuery<Admin2faStatusDto>({
    queryKey: ["admin", "2fa-status"],
    queryFn: () => api.get("api/admin/2fa/status").json(),
  });
}

export function useAdmin2faSetup() {
  return useMutation<Admin2faSetupDto, Error, void>({
    mutationFn: () => api.post("api/admin/2fa/setup").json(),
  });
}

export function useAdmin2faEnable() {
  const qc = useQueryClient();
  return useMutation<Admin2faStatusDto, Error, Admin2faConfirmBody>({
    mutationFn: (body) => api.post("api/admin/2fa/enable", { json: body }).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "2fa-status"] }),
  });
}

export function useAdmin2faDisable() {
  const qc = useQueryClient();
  return useMutation<Admin2faStatusDto, Error, Admin2faVerifyBody>({
    mutationFn: (body) => api.post("api/admin/2fa/disable", { json: body }).json(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "2fa-status"] }),
  });
}

// ── Audit log ───────────────────────────────────────────────────────────

export function useAdminAuditLog(params: {
  action?: string;
  actor_id?: number;
  target_type?: string;
  target_id?: number;
  page?: number;
  page_size?: number;
}) {
  return useQuery<AdminAuditLogListDto>({
    queryKey: ["admin", "audit", params],
    queryFn: () => {
      const sp = new URLSearchParams();
      if (params.action) sp.set("action", params.action);
      if (params.actor_id !== undefined) sp.set("actor_id", String(params.actor_id));
      if (params.target_type) sp.set("target_type", params.target_type);
      if (params.target_id !== undefined) sp.set("target_id", String(params.target_id));
      sp.set("page", String(params.page ?? 1));
      sp.set("page_size", String(params.page_size ?? 50));
      return api.get("api/admin/audit", { searchParams: sp }).json();
    },
    placeholderData: (prev) => prev,
  });
}
