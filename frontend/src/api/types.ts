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
  // V12-UI — gallery URLs (``/media/service/...`` or ``https://...``)
  // attached to the service by its owner. Capped at 6 server-side.
  photo_urls?: string[];
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
  admin: number;
  prefix: "admin" | "arbiter" | "vip" | null;
  is_admin?: boolean;
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
  // Item 11 — portfolio breakdown surfaced from the backend
  // ``UserOut`` / ``UserPublicOut``. Already maintained on the
  // ``User`` row by ``services_deals`` (see
  // ``tests/e2e/test_deals_arbitration.py``) and shown next to
  // ``deals_count`` in ``<ProfileStatsGrid />``.
  deals_success: number;
  deals_failed: number;
  deals_arbitrage: number;
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
  // ISO-3166-1 alpha-2 country code chosen by the profile owner. The
  // canonical list (code → russian name → flag emoji) lives in
  // ``frontend/src/lib/countries.ts`` (static, no backend lookup).
  // ``null`` means "user hasn't picked a country yet" — UI hides the
  // flag chip in that case rather than rendering a placeholder.
  country?: string | null;
  // Items 13/15 — fiat currency code the user picked as their
  // "main" balance shown on the ProfilePage fiat-balance card.
  // ``null`` means "not picked" — UI falls back to USD.
  display_currency_code?: string | null;
}

export type DealStatus =
  | "cancelled"
  | "pending_confirmation"
  | "pending_payment"
  | "pending_topup"
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
  // Item 21 — counterparty avatar URLs surfaced for deal list + detail.
  buyer_photo_url?: string | null;
  seller_photo_url?: string | null;
  description: string;
  topup_deposit_id?: number | null;
  commission_paid?: boolean;
  topup_invoice?: DealTopupInvoiceDto | null;
  status: DealStatus | string;
  confirm_buyer: boolean;
  confirm_seller: boolean;
  role: "buyer" | "seller";
  created_at: string | null;
  currency_code: string | null;
  amount: number;
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
  // Upstream invoice provider chosen by the buyer at deal-create
  // time. ``"cryptobot"`` (default) keeps legacy rows backwards-
  // compatible.
  payment_provider?: "cryptobot" | "crystalpay" | string;
}

export interface DealTopupInvoiceDto {
  deposit_id: number;
  pay_url: string;
  total: string | number;
  topup_principal: string | number;
  commission: string | number;
  paid_total?: string | number;
  currency_code: string;
  provider: string;
  expires_at?: string | null;
}

export interface DealCreateWithTopupResponseDto {
  deal: DealDto;
  // ``null`` when the buyer's balance fully covers amount + commission
  // and the backend skips the invoice path.
  invoice: DealTopupInvoiceDto | null;
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

// H-1 — ``InvoiceDto`` / ``DepositDto`` retired alongside the legacy
// ``/api/payments/deposit*`` endpoints. The multi-currency wallet
// flow uses ``WalletDepositDto`` / ``WalletDepositCreateReq`` below.

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
  code_length: number;
  ttl_seconds: number;
}

export interface AccountTransferStartDto {
  delivered: boolean;
  expires_at: string;
  code_length: number;
  ttl_seconds: number;
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
  // Distinguishes fiat invoices (``"fiat"`` — UAH/RUB/USD) from
  // crypto invoices (``"crypto"`` — USDT/TON/...). Surfaced so the
  // deposit page can filter the dropdown to fiat-only options.
  kind?: "crypto" | "fiat" | string;
}

export interface WalletBalanceDto {
  currency: CurrencyDto;
  amount: number;
  locked: number;
  total: number;
  updated_at: string | null;
  // Audit M-7 — string mirrors of the three money fields. The
  // ``amount`` / ``locked`` / ``total`` fields are typed ``number``
  // for backward compatibility, but JavaScript's IEEE-754 double
  // silently loses precision at the 10^10-ish scale USDT can hit.
  // Always prefer ``*_str`` for any value that round-trips back to
  // the API (e.g. the "Все" button on the withdraw form pre-filling
  // the amount input) so the user-visible string passes straight
  // through without going through ``parseFloat``.
  amount_str: string;
  locked_str: string;
  total_str: string;
}

export interface WalletDepositDto {
  id: number;
  currency: CurrencyDto;
  amount: number;
  status: "pending" | "paid" | "expired" | string;
  pay_url: string;
  invoice_id: string;
  // Routing tag chosen by the user at deposit-create time. ``"wallet"``
  // (default, legacy semantics) credits ``UserBalance`` for the chosen
  // currency. ``"trust"`` credits ``User.trust_deposit_balance``
  // instead — non-spendable, non-withdrawable, surfaced only on the
  // public ``deposit`` field of ``UserCardDto``.
  purpose: "wallet" | "trust" | string;
  // Upstream payment provider that issued this invoice. Drives the
  // badge on the deposit list/card and is preserved on the wire so a
  // page refresh after the back-end finishes routing can still render
  // the correct logo.
  provider: "cryptobot" | "crystalpay" | string;
  created_at: string;
  paid_at: string | null;
}

export interface WalletDepositCreateBody {
  currency_code: string;
  amount: string;
  // See ``WalletDepositDto.purpose``. Optional on the wire; the
  // backend defaults to ``"wallet"`` when omitted.
  purpose?: "wallet" | "trust";
  // Selects the upstream payment provider. ``"cryptobot"`` (default)
  // hits Crypto Pay; ``"crystalpay"`` hits the Crystalpay v3 API.
  provider?: "cryptobot" | "crystalpay";
}

export interface WalletWithdrawalDto {
  id: number;
  currency: CurrencyDto;
  amount: number;
  address: string | null;
  status: "pending" | "approved" | "sent" | "rejected" | string;
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

export type AdminUserPrefix = "admin" | "arbiter" | "vip" | null;

export interface AdminUserListItemDto {
  id: number;
  tg_user_id: number;
  username: string | null;
  display_name: string;
  photo_url: string | null;
  prefix: AdminUserPrefix;
  is_admin: boolean;
  is_arbiter: boolean;
  is_vip: boolean;
  is_banned: boolean;
  is_frozen: boolean;
  // Item 12 — the trust-deposit balance is what the public profile
  // surfaces as ``deposit``.
  trust_deposit_balance: number;
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
  // Item 12 — see ``AdminUserListItemDto.trust_deposit_balance``.
  trust_deposit_balance: number;
  rating_auto: number;
  rating_manual: number | null;
  rating_effective: number;
  good: number;
  bad: number;
  deals_total: number;
  deals_success: number;
  deals_failed: number;
  deals_arbitrage: number;
  deals_sum_override: number;
  is_admin: boolean;
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

// Audit L-10 — the public backend route still accepts ``"any"`` as the
// "no filter" sentinel (see ``backend/app/routers/admin/users.py`` —
// the union is preserved there for OpenAPI / wire compatibility), but
// the frontend now omits the param entirely instead of round-tripping
// a magic string. ``role``/``status`` being ``undefined`` here means
// the same thing as ``"any"`` on the wire.
export type AdminUserRoleFilter = "admin" | "arbiter" | "vip" | "regular";
export type AdminUserStatusFilter = "active" | "banned" | "frozen";

export interface AdminListUsersQuery {
  q?: string;
  role?: AdminUserRoleFilter;
  status?: AdminUserStatusFilter;
  sort?: "created_desc" | "created_asc" | "rating" | "deals";
  page?: number;
  page_size?: number;
}

// ── Admin: deals (PR-B) ────────────────────────────────────────────────

export interface AdminDealListItemDto {
  id: number;
  status: DealStatus | string;
  currency_code: string | null;
  amount: string;
  commission_amount: string | null;
  buyer_id: number;
  buyer_username: string | null;
  seller_id: number;
  seller_username: string | null;
  created_at: string;
  in_progress_at: string | null;
  completed_at: string | null;
  has_arbitration: boolean;
  has_cancel_request: boolean;
}

export interface AdminDealListDto {
  items: AdminDealListItemDto[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminBalanceSnapshotDto {
  user_id: number;
  username: string | null;
  display_name: string;
  currency_code: string | null;
  amount: string;
  locked: string;
  total: string;
}

export interface AdminDealEventDto {
  at: string;
  kind: string;
  actor: string | null;
  description: string;
}

export interface AdminDealDetailDto {
  id: number;
  status: DealStatus | string;
  description: string;
  currency_code: string | null;
  amount: string;
  commission_amount: string | null;
  commission_paid: boolean;
  topup_deposit_id?: number | null;
  buyer: AdminBalanceSnapshotDto;
  seller: AdminBalanceSnapshotDto;
  created_at: string;
  in_progress_at: string | null;
  completed_at: string | null;
  cancellation_initiator: string | null;
  cancellation_reason: string | null;
  cancellation_requested_at: string | null;
  arbitration_initiator: string | null;
  arbitration_reason: string | null;
  arbitration_resolved_by_id: number | null;
  arbitration_resolved_by_username: string | null;
  arbitration_resolution: string | null;
  arbitration_resolved_at: string | null;
  confirm_buyer: boolean;
  confirm_seller: boolean;
  events: AdminDealEventDto[];
  messages: AdminDealMessageDto[];
  pending_approvals?: AdminApprovalDto[];
}

export interface AdminApprovalDto {
  id: number;
  action: string;
  target_type: string;
  target_id: number;
  status: "pending" | "approved" | "executed" | "rejected" | string;
  requested_by_id: number | null;
  approved_by_id?: number | null;
  executed_by_id?: number | null;
  currency_code?: string | null;
  amount?: string | number | null;
  amount_usd_estimate?: string | number | null;
  reason?: string | null;
  payload?: Record<string, unknown> | null;
  created_at: string;
  approved_at?: string | null;
  executed_at?: string | null;
  rejected_at?: string | null;
}

export interface AdminDealActionResultDto {
  deal: AdminDealDetailDto;
  pending_approval?: AdminApprovalDto | null;
}

export interface AdminDealMessageDto {
  id: number;
  deal_id: number;
  sender_id: number;
  sender_username: string | null;
  sender_display_name: string;
  text: string;
  attachments: { id: number; url: string; mime: string | null }[];
  created_at: string;
}

export interface AdminListDealsQuery {
  // Audit L-10 — ``undefined`` (param omitted) is the canonical "no
  // filter" value; the previous ``"any"`` literal is no longer part
  // of the union on the frontend.
  status?: DealStatus | string;
  currency?: string;
  min_amount?: number;
  max_amount?: number;
  has_arbitration?: boolean;
  has_cancel_request?: boolean;
  buyer_id?: number;
  seller_id?: number;
  page?: number;
  page_size?: number;
}

// ── Admin: arbitration (PR-B) ──────────────────────────────────────────

export interface AdminArbitrationCountersDto {
  new: number;
  in_progress: number;
  closed: number;
}

export interface AdminArbitrationListDto {
  items: AdminDealListItemDto[];
  counters: AdminArbitrationCountersDto;
  queue: "new" | "in_progress" | "closed";
}

// ── Admin: content editing (PR-B) ──────────────────────────────────────

export interface AdminServiceItemDto {
  id: number;
  owner_id: number;
  category_id: number;
  category_slug: string | null;
  title: string;
  description: string;
  price: number;
  status: string;
  ban_reason: string | null;
  views: number;
  deals_count: number;
  deposit: number;
  rating_manual: number | null;
  created_at: string;
}

export interface AdminServiceListDto {
  items: AdminServiceItemDto[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminServiceUpdateBody {
  title?: string;
  description?: string;
  price?: number;
  deposit?: number;
  views?: number;
  deals_count?: number;
  rating_manual?: number | null;
  clear_rating?: boolean;
  status?: "draft" | "active" | "paused" | "banned";
  ban_reason?: string;
}

export interface AdminReviewItemDto {
  id: number;
  deal_id: number | null;
  author_id: number;
  author_username: string | null;
  target_id: number;
  target_username: string | null;
  rating: number;
  text: string;
  created_at: string;
}

export interface AdminReviewListDto {
  items: AdminReviewItemDto[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminReviewUpsertBody {
  target_id?: number;
  author_id?: number;
  deal_id?: number | null;
  rating: number;
  text: string;
}

export interface AdminCommentItemDto {
  id: number;
  service_id: number;
  author_id: number;
  author_username: string | null;
  text: string;
  rating: number | null;
  created_at: string;
}

export interface AdminCommentListDto {
  items: AdminCommentItemDto[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminCommentUpdateBody {
  text?: string;
  rating?: number;
  clear_rating?: boolean;
}

// ── Admin PR-CDE: wallets / finance / settings / broadcasts / analytics ─

export interface AdminUserBalanceDto {
  user_id: number;
  username: string | null;
  display_name: string;
  currency_id: number;
  currency_code: string;
  currency_name: string;
  decimals: number;
  amount: string;
  locked: string;
  total: string;
  usd_rate?: string | number | null;
  usd_estimate?: string | number | null;
  usd_rate_source?: string | null;
  usd_rate_observed_at?: string | null;
  updated_at: string | null;
}

export interface AdminWalletListItemDto {
  user_id: number;
  username: string | null;
  display_name: string;
  photo_url: string | null;
  is_admin: boolean;
  is_arbiter: boolean;
  is_vip: boolean;
  is_banned: boolean;
  is_frozen: boolean;
  balances: AdminUserBalanceDto[];
  total_usd_estimate?: string | number | null;
  usd_estimate_missing_rates?: string[];
}

export interface AdminWalletListDto {
  items: AdminWalletListItemDto[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminWalletAdjustBody {
  currency_code: string;
  amount: number;
  reason?: string;
}

export interface AdminCurrencyRateDto {
  currency_id: number;
  currency_code: string;
  usd_rate: string | number;
  source: string;
  observed_at: string;
  updated_at?: string | null;
  updated_by_id?: number | null;
}

export interface AdminCurrencyRateUpsertBody {
  currency_code: string;
  usd_rate: number;
  source?: string;
  observed_at?: string | null;
}

export interface AdminDepositDto {
  id: number;
  user_id: number;
  username: string | null;
  display_name: string;
  currency_code: string;
  amount: string;
  status: string;
  provider_invoice_id: string;
  pay_url: string;
  created_at: string;
  paid_at: string | null;
}

export interface AdminDepositListDto {
  items: AdminDepositDto[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminWithdrawalDto {
  id: number;
  user_id: number;
  username: string | null;
  display_name: string;
  currency_code: string;
  amount: string;
  address: string | null;
  status: string;
  admin_note: string;
  created_at: string;
  processed_at: string | null;
}

export interface AdminWithdrawalListDto {
  items: AdminWithdrawalDto[];
  counters: Record<string, number>;
}

export interface AdminWithdrawalDecisionBody {
  action: "approve" | "reject" | "mark_sent";
  note?: string;
}

export interface AdminSettingsDto {
  deal_commission_percent: number;
  vip_commission_percent: number;
  inactivity_pending_confirmation_days: number;
  inactivity_pending_cancellation_days: number;
  pending_topup_expiry_hours: number;
  max_active_services_per_user: number;
  maintenance_enabled: boolean;
  maintenance_message: string;
  auto_withdraw_enabled: boolean;
  pin_reset_price_usd: number;
  faq_stats_badge_enabled: boolean;
  faq_stats_users: number;
  faq_stats_deals: number;
  faq_stats_total_usd: number;
}

export interface AdminSettingsUpdateBody {
  deal_commission_percent?: number;
  vip_commission_percent?: number;
  inactivity_pending_confirmation_days?: number;
  inactivity_pending_cancellation_days?: number;
  pending_topup_expiry_hours?: number;
  max_active_services_per_user?: number;
  maintenance_enabled?: boolean;
  maintenance_message?: string;
  auto_withdraw_enabled?: boolean;
  pin_reset_price_usd?: number;
  faq_stats_badge_enabled?: boolean;
  faq_stats_users?: number;
  faq_stats_deals?: number;
  faq_stats_total_usd?: number;
}

export interface AdminCategoryDto {
  id: number;
  slug: string;
  name: string;
  icon: string;
}

export interface AdminCategoryUpsertBody {
  slug: string;
  name: string;
  icon?: string;
}

export interface AdminCurrencyDto {
  id: number;
  code: string;
  name: string;
  network: string;
  icon_url: string;
  decimals: number;
  min_deposit: number;
  min_withdraw: number;
  is_active: boolean;
  sort_order: number;
  address_regex?: string;
  kind?: "crypto" | "fiat" | string;
}

export interface AdminCurrencyUpsertBody {
  code: string;
  name?: string;
  network?: string;
  icon_url?: string;
  decimals?: number;
  min_deposit?: number;
  min_withdraw?: number;
  is_active?: boolean;
  sort_order?: number;
  address_regex?: string;
  kind?: "crypto" | "fiat";
}

export interface AdminBroadcastDto {
  id: number;
  actor_id: number;
  actor_username: string | null;
  title: string;
  body: string;
  deeplink: string | null;
  audience_role: string | null;
  audience_active_days: number | null;
  audience_min_deals: number | null;
  audience_created_after: string | null;
  audience_created_before: string | null;
  audience_language: string | null;
  dispatch_inapp: boolean;
  dispatch_dm: boolean;
  status: string;
  total_recipients: number;
  delivered_count: number;
  failed_count: number;
  scheduled_at: string | null;
  sent_at: string | null;
  created_at: string;
}

export interface AdminBroadcastListDto {
  items: AdminBroadcastDto[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminBroadcastCreateBody {
  title?: string;
  body: string;
  deeplink?: string;
  audience_role?: "admin" | "arbiter" | "vip" | "regular";
  audience_active_days?: number;
  audience_min_deals?: number;
  audience_created_after?: string;
  audience_created_before?: string;
  audience_language?: string;
  dispatch_inapp?: boolean;
  dispatch_dm?: boolean;
  scheduled_at?: string;
}

export interface AdminBroadcastPreviewDto {
  total_recipients: number;
}

export interface AdminAnalyticsKpiDto {
  dau: number;
  wau: number;
  mau: number;
  new_users_24h: number;
  new_users_7d: number;
  deals_24h: number;
  deals_7d: number;
  deals_volume_usd_30d: number;
  open_arbitration: number;
  pending_withdrawals: number;
}

export interface AdminAnalyticsSeriesPointDto {
  date: string;
  value: number;
}

export interface AdminAnalyticsSeriesDto {
  deals_count_30d: AdminAnalyticsSeriesPointDto[];
  deals_volume_30d: AdminAnalyticsSeriesPointDto[];
  new_users_30d: AdminAnalyticsSeriesPointDto[];
  deposits_30d: AdminAnalyticsSeriesPointDto[];
  withdrawals_30d: AdminAnalyticsSeriesPointDto[];
}

export interface AdminAnalyticsTopUserDto {
  user_id: number;
  username: string | null;
  display_name: string;
  value: number;
}

export interface AdminAnalyticsTopListsDto {
  top_sellers: AdminAnalyticsTopUserDto[];
  top_buyers: AdminAnalyticsTopUserDto[];
  top_arbiters: AdminAnalyticsTopUserDto[];
}

export interface AdminSystemStatusDto {
  db_ok: boolean;
  db_latency_ms: number | null;
  redis_ok: boolean;
  redis_latency_ms: number | null;
  cryptobot_configured: boolean;
  bot_configured: boolean;
  backend_version: string;
  started_at: string | null;
  uptime_seconds: number;
  alerts?: OperationalAlertDto[];
}

export interface OperationalAlertDto {
  name: string;
  severity: "info" | "warning" | "critical";
  count: number;
  detail: string;
}

export interface Admin2faStatusDto {
  enabled: boolean;
}

export interface Admin2faSetupDto {
  secret: string;
  otpauth_url: string;
}

export interface Admin2faConfirmBody {
  secret: string;
  code: string;
}

export interface Admin2faVerifyBody {
  code: string;
}

export interface AdminAuditLogDto {
  id: number;
  actor_id: number | null;
  actor_username: string | null;
  action: string;
  target_type: string | null;
  target_id: number | null;
  reason: string | null;
  payload: Record<string, unknown> | null;
  ip: string | null;
  created_at: string;
}

export interface AdminAuditLogListDto {
  items: AdminAuditLogDto[];
  total: number;
  page: number;
  page_size: number;
}

/**
 * Subset of ``AppSettings`` exposed via ``GET /api/settings/public``
 * for unauthenticated / pre-login consumption. The frontend uses
 * these to render the commission preview on ``CreateDealPage`` and
 * to drive the address-field visibility on ``WalletWithdrawPage``.
 */
export interface PublicSettingsDto {
  deal_commission_percent: number;
  vip_commission_percent: number;
  auto_withdraw_enabled: boolean;
  faq_stats_badge_enabled: boolean;
}

export interface MaintenanceStatusDto {
  enabled: boolean;
  message: string;
}
