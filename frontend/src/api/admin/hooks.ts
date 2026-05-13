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
  AdminArbitrationListDto,
  AdminCommentItemDto,
  AdminCommentUpdateBody,
  AdminDashboardDto,
  AdminDealDetailDto,
  AdminDealListDto,
  AdminListDealsQuery,
  AdminListUsersQuery,
  AdminReviewItemDto,
  AdminReviewUpsertBody,
  AdminServiceItemDto,
  AdminServiceUpdateBody,
  AdminUserDetailDto,
  AdminUserListDto,
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
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["admin", "deals"] });
      qc.invalidateQueries({ queryKey: ["admin", "deal", vars.dealId] });
      qc.invalidateQueries({ queryKey: ["admin", "arbitration"] });
      qc.invalidateQueries({ queryKey: ["admin", "dashboard"] });
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
