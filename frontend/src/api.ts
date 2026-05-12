import { getInitData } from "@/telegram";

export interface UserShort {
  id: number;
  tg_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  photo_url: string | null;
  rating: number;
}

export interface User extends UserShort {
  balance: number;
  frozen: number;
  insurance: number;
  deals_total: number;
  deals_success: number;
  is_admin: boolean;
  is_banned: boolean;
  created_at: string;
}

export type DealStatus =
  | "draft"
  | "awaiting_payment"
  | "funded"
  | "completed"
  | "cancelled"
  | "disputed"
  | "refunded";

export interface Deal {
  id: number;
  title: string;
  description: string;
  amount: number;
  commission: number;
  status: DealStatus;
  buyer: UserShort;
  seller: UserShort;
  creator_id: number;
  created_at: string;
  funded_at: string | null;
  completed_at: string | null;
  dispute_reason: string | null;
}

export interface PublicSettings {
  commission_percent: number;
  insurance_deposit: number;
  welcome_message: string;
}

export interface Transaction {
  id: number;
  type: string;
  amount: number;
  deal_id: number | null;
  note: string | null;
  created_at: string;
}

export interface AdminStats {
  users_total: number;
  users_active_7d: number;
  deals_total: number;
  deals_in_escrow: number;
  volume_total: number;
  commission_total: number;
}

const BASE = "/api";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": getInitData(),
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = "Request failed";
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      detail = res.statusText || detail;
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  me: () => request<User>("/me"),
  settings: () => request<PublicSettings>("/settings"),
  searchUsers: (q: string) =>
    request<UserShort[]>(`/users/search?q=${encodeURIComponent(q)}`),
  getUser: (tg_id: number) => request<UserShort>(`/users/${tg_id}`),
  transactions: () => request<Transaction[]>("/balance/transactions"),
  deposit: (amount: number, note?: string) =>
    request<User>("/balance/deposit", {
      method: "POST",
      body: JSON.stringify({ amount, note }),
    }),
  withdraw: (amount: number, note?: string) =>
    request<User>("/balance/withdraw", {
      method: "POST",
      body: JSON.stringify({ amount, note }),
    }),
  lockInsurance: () => request<User>("/insurance/lock", { method: "POST" }),
  unlockInsurance: () => request<User>("/insurance/unlock", { method: "POST" }),
  listDeals: (status?: DealStatus) =>
    request<Deal[]>(`/deals${status ? `?status=${status}` : ""}`),
  getDeal: (id: number) => request<Deal>(`/deals/${id}`),
  createDeal: (body: {
    title: string;
    description: string;
    amount: number;
    role: "buyer" | "seller";
    counterparty_tg_id?: number;
    counterparty_username?: string;
  }) =>
    request<Deal>("/deals", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  dealAction: (
    id: number,
    action: "fund" | "confirm" | "cancel" | "open_dispute",
    reason?: string,
  ) =>
    request<Deal>(`/deals/${id}/action`, {
      method: "POST",
      body: JSON.stringify({ action, reason }),
    }),

  admin: {
    stats: () => request<AdminStats>("/admin/stats"),
    listUsers: (q = "") =>
      request<User[]>(`/admin/users?q=${encodeURIComponent(q)}`),
    listDeals: (status?: DealStatus) =>
      request<Deal[]>(`/admin/deals${status ? `?status=${status}` : ""}`),
    settings: () => request<PublicSettings>("/admin/settings"),
    updateSettings: (body: Partial<PublicSettings>) =>
      request<PublicSettings>("/admin/settings", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    updateUser: (
      id: number,
      body: {
        balance_delta?: number;
        insurance_delta?: number;
        is_banned?: boolean;
        is_admin?: boolean;
        rating?: number;
        note?: string;
      },
    ) =>
      request<User>(`/admin/users/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    forceRelease: (id: number) =>
      request<Deal>(`/admin/deals/${id}/release`, { method: "POST" }),
    forceRefund: (id: number) =>
      request<Deal>(`/admin/deals/${id}/refund`, { method: "POST" }),
  },
};
