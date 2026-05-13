export interface CategoryDto {
  id: number;
  slug: string;
  name: string;
  icon_key: string;
  services_count: number;
}

export interface ServiceDto {
  id: number;
  owner_username: string;
  title: string;
  description: string;
  price: number;
  currency: string;
  status: string;
  category: CategoryDto;
  created_at?: string | null;
}

export interface ServiceOwnerDto {
  id: number;
  username: string | null;
  display_name: string;
  photo_url: string | null;
  rating: number;
  deals_count: number;
  good: number;
  bad: number;
  is_admin: boolean;
  is_moderator: boolean;
  is_arbiter: boolean;
}

export interface ServiceDetailDto extends ServiceDto {
  owner: ServiceOwnerDto | null;
  comments_count: number;
  rating_avg: number | null;
  rating_count: number;
}

export interface ServiceCommentDto {
  id: number;
  service_id: number;
  author_id: number;
  author_username: string | null;
  author_display_name: string;
  author_photo_url: string | null;
  text: string;
  rating: number | null;
  created_at: string;
}

export interface UserCardDto {
  id: number;
  user_id: number;
  username: string;
  display_name: string;
  photo_url: string | null;
  balance: number;
  admin: number;
  prefix: "admin" | "moderator" | "arbiter" | "vip" | null;
  is_admin?: boolean;
  is_moderator?: boolean;
  is_arbiter?: boolean;
  is_vip?: boolean;
  is_banned?: boolean;
  is_frozen?: boolean;
  good: number;
  bad: number;
  deposit: number;
  rating: number;
  reviews_count: number;
  deals_count: number;
  deals_sum: number;
  online: boolean;
  banner_url?: string | null;
  description: string;
  forums: { name: string; url: string }[];
  dm_deals?: boolean;
  dm_deposits?: boolean;
  dm_system?: boolean;
  is_anonymous_deals?: boolean;
  is_hidden_profile?: boolean;
}

export type DealStatus =
  | "cancelled"
  | "pending_confirmation"
  | "pending_payment"
  | "in_progress"
  | "completed"
  | "arbitration"
  | "resolved_for_buyer"
  | "resolved_for_seller"
  | "pending_cancellation"
  | "cancelled_for_inactivity";

export interface DealDto {
  id: number;
  buyer: string;
  seller: string;
  sum: number;
  description: string;
  pay_comission: string;
  status: DealStatus | string;
  confirm_buyer: boolean;
  confirm_seller: boolean;
  role: "buyer" | "seller";
  created_at: string | null;
  currency_code: string | null;
  amount: number | null;
  commission_amount: number | null;
  in_progress_at: string | null;
  completed_at: string | null;
  cancellation_initiator: "buyer" | "seller" | "other" | null;
  cancellation_reason: string | null;
  cancellation_requested_at: string | null;
  arbitration_initiator: "buyer" | "seller" | "other" | null;
  arbitration_reason: string | null;
  arbitration_resolved_by: string | null;
  arbitration_resolution: "buyer" | "seller" | null;
  arbitration_resolved_at: string | null;
}

export interface ReviewDto {
  id: number;
  deal_id: number | null;
  author_username: string;
  target_username: string;
  rating: number;
  text: string;
  created_at: string;
}

export interface NotificationDto {
  id: number;
  type: "deals" | "deposits" | "system" | string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  is_read: boolean;
  created_at: string;
}

export interface NotificationCountersDto {
  all: number;
  deals: number;
  deposits: number;
  system: number;
  unread: number;
}

export interface SupportPersonDto {
  id: number;
  user_id: number;
  username: string;
  display_name: string;
  photo_url: string | null;
  admin: number;
  prefix: "admin" | "arbiter";
}

export interface InvoiceDto {
  invoice_id: string | number;
  pay_url: string;
  amount: number;
  asset: string;
}

export interface DepositDto {
  id: number;
  amount: number;
  status: string;
  created_at: string;
  paid_at: string | null;
}

export interface PinStatusDto {
  has_pin: boolean;
  attempts_left: number;
  locked_until: string | null;
  max_attempts: number;
  session_ttl_seconds: number;
}

export interface PinTokenDto {
  token: string;
  expires_at: string;
}

export interface PinResetRequestDto {
  delivered: boolean;
  expires_at: string;
}

export interface AccountTransferStatusDto {
  has_active: boolean;
  expires_at: string | null;
}

export interface AccountTransferStartDto {
  delivered: boolean;
  expires_at: string;
}

export interface AccountTransferConfirmDto {
  ok: boolean;
  tg_user_id: number;
}

export interface CurrencyDto {
  id: number;
  code: string;
  name: string;
  network: string;
  icon_url: string;
  decimals: number;
  min_deposit: number;
  min_withdraw: number;
}

export interface WalletBalanceDto {
  currency: CurrencyDto;
  amount: number;
  locked: number;
  total: number;
  updated_at: string | null;
}

export interface WalletDepositDto {
  id: number;
  currency: CurrencyDto;
  amount: number;
  status: "pending" | "paid" | "expired" | string;
  pay_url: string;
  invoice_id: string;
  created_at: string;
  paid_at: string | null;
}

export interface WalletWithdrawalDto {
  id: number;
  currency: CurrencyDto;
  amount: number;
  address: string;
  status: "pending" | "approved" | "sent" | "rejected" | string;
  locked_until: string | null;
  admin_note: string;
  created_at: string;
  processed_at: string | null;
}

// ── Admin panel ─────────────────────────────────────────────────────────

export interface AdminDashboardDto {
  total_users: number;
  new_users_24h: number;
  new_users_7d: number;
  online_users_5min: number;
  total_deals: number;
  open_deals: number;
  open_arbitration: number;
  total_services: number;
  active_services: number;
  banned_users: number;
  frozen_users: number;
  admins: number;
  arbiters: number;
  vips: number;
}

export type AdminUserPrefix = "admin" | "moderator" | "arbiter" | "vip" | null;

export interface AdminUserListItemDto {
  id: number;
  tg_user_id: number;
  username: string | null;
  display_name: string;
  photo_url: string | null;
  prefix: AdminUserPrefix;
  is_admin: boolean;
  is_moderator: boolean;
  is_arbiter: boolean;
  is_vip: boolean;
  is_banned: boolean;
  is_frozen: boolean;
  balance: number;
  deposit_total: number;
  rating: number;
  deals_total: number;
  deals_success: number;
  last_ip: string | null;
  last_login_at: string | null;
  created_at: string;
}

export interface AdminUserListDto {
  items: AdminUserListItemDto[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminUserDetailDto {
  id: number;
  tg_user_id: number;
  username: string | null;
  display_name: string;
  photo_url: string | null;
  banner_url: string | null;
  description: string;
  balance: number;
  deposit_total: number;
  rating_auto: number;
  rating_manual: number | null;
  rating_effective: number;
  good: number;
  bad: number;
  deals_total: number;
  deals_success: number;
  deals_failed: number;
  deals_arbitrage: number;
  is_admin: boolean;
  is_moderator: boolean;
  is_arbiter: boolean;
  is_vip: boolean;
  is_banned: boolean;
  ban_reason: string | null;
  is_frozen: boolean;
  freeze_reason: string | null;
  is_anonymous_deals: boolean;
  is_hidden_profile: boolean;
  has_pin: boolean;
  last_ip: string | null;
  last_login_at: string | null;
  login_count: number;
  created_at: string;
}

export interface AdminListUsersQuery {
  q?: string;
  role?: "admin" | "moderator" | "arbiter" | "vip" | "regular" | "any";
  status?: "any" | "active" | "banned" | "frozen";
  sort?: "created_desc" | "created_asc" | "rating" | "deals" | "deposit";
  page?: number;
  page_size?: number;
}
