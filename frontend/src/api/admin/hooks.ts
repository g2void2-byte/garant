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
  AdminDashboardDto,
  AdminListUsersQuery,
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
