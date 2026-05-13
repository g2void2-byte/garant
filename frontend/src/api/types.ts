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

export interface UserCardDto {
  id: number;
  user_id: number;
  username: string;
  display_name: string;
  photo_url: string | null;
  balance: number;
  admin: number;
  prefix: "admin" | "arbiter" | null;
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
  forums: { name?: string; url?: string }[];
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
