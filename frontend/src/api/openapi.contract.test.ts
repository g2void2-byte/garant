/**
 * Contract tests that validate frontend mock fixtures + DTO types
 * against the FastAPI OpenAPI schema (``frontend/openapi.json``,
 * regenerated from ``backend/app/main.py`` via
 * ``npm run generate:api-types``).
 *
 * The tests are entirely compile-time: ``as const satisfies T`` makes
 * ``tsc`` reject any shape drift between the backend and the
 * fixtures / DTO types used by the app, so the CI ``typecheck`` stage
 * fails the build when the contract changes.
 *
 * What's covered:
 *   - ``components.schemas`` entries we depend on exist
 *   - representative e2e fixture payloads match the backend shape
 *     (UserCard / Deal / Review / WalletBalance / Currency / Service / WalletDeposit / PinStatus)
 *   - frontend ``UserCardDto`` / ``DealDto`` / ``ServiceDto`` / etc. align with their
 *     OpenAPI counterparts on the fields the UI reads
 */

import { describe, expect, it } from "vitest";
import openapi from "../../openapi.json";
import type { components } from "./openapi.generated";
import type {
  AdminDealDetailDto,
  AdminUserDetailDto,
  CurrencyDto,
  DealCreateWithTopupResponseDto,
  DealDto,
  DealMessageDto,
  MediaDto,
  PinStatusDto,
  ReviewDto,
  ServiceDetailDto,
  ServiceDto,
  SupportPersonDto,
  UserCardDto,
  WalletBalanceDto,
  WalletDepositDto,
} from "./types";

type Schemas = components["schemas"];
type AdminDealDetailOutSchema = Schemas["AdminDealDetailOut"];
type AdminUserDetailOutSchema = Schemas["AdminUserDetailOut"];
type DealOutSchema = Schemas["DealOut"];
type DealCreateWithTopupOutSchema = Schemas["DealCreateWithTopupOut"];
type CurrencyOutSchema = Schemas["CurrencyOut"];
type DealMessageOutSchema = Schemas["DealMessageOut"];
type MediaOutSchema = Schemas["MediaOut"];
type WalletBalanceOutSchema = Schemas["WalletBalanceOut"];
type WalletDepositOutSchema = Schemas["WalletDepositOut"];
type PinStatusOutSchema = Schemas["PinStatusOut"];
type ReviewOutSchema = Schemas["ReviewOut"];
type ServiceOutSchema = Schemas["ServiceOut"];
type ServiceDetailOutSchema = Schemas["ServiceDetailOut"];
type SupportPersonOutSchema = Schemas["SupportPersonOut"];
type UserOutSchema = Schemas["UserOut"];

// ---------------------------------------------------------------------------
// 1. Compile-time assertions: representative fixture payloads must
//    satisfy the OpenAPI schema. ``tsc`` enforces this — if a
//    backend field is renamed or its nullability flipped, the
//    matching ``satisfies`` clause below stops compiling.
// ---------------------------------------------------------------------------

const meFixture = {
  id: 111,
  user_id: 111,
  username: null,
  display_name: "TestBuyer",
  photo_url: null,
  admin: 0,
  prefix: null,
  is_admin: false,
  is_arbiter: false,
  is_vip: false,
  is_banned: false,
  is_frozen: false,
  good: 0,
  bad: 0,
  deposit: 0,
  rating: 0,
  reviews_count: 0,
  deals_count: 0,
  deals_success: 0,
  deals_failed: 0,
  deals_arbitrage: 0,
  deals_sum: 0,
  online: true,
  banner_url: null,
  description: "",
  forums: [],
  is_hidden_profile: false,
  dm_deals: true,
  dm_deposits: true,
  dm_system: true,
  is_anonymous_deals: false,
} as const satisfies UserOutSchema;

const dealFixture = {
  id: 17,
  buyer: "testbuyer",
  seller: "alice",
  description: "Logo design package",
  status: "in_progress",
  confirm_buyer: false,
  confirm_seller: false,
  role: "buyer",
  created_at: new Date(0).toISOString(),
  currency_code: "USDT",
  amount: 100,
  commission_amount: 5,
  commission_paid: true,
  topup_deposit_id: null,
  topup_invoice: null,
  in_progress_at: null,
  completed_at: null,
  cancellation_initiator: null,
  cancellation_reason: null,
  cancellation_requested_at: null,
  arbitration_initiator: null,
  arbitration_reason: null,
  arbitration_resolved_by: null,
  arbitration_resolution: null,
  arbitration_resolved_at: null,
  payment_provider: "cryptobot",
} as const satisfies DealOutSchema;

const nullableDealFixture = {
  ...dealFixture,
  buyer: null,
  seller: null,
  role: "unknown-role",
} as const satisfies DealOutSchema;

const mediaFixture = {
  id: 701,
  kind: "deal",
  url: "/media/deal/701",
  name: "proof.png",
  size: 1024,
  content_type: "image/png",
  created_at: null,
} as const satisfies MediaOutSchema;

const dealMessageFixture = {
  id: 801,
  deal_id: 17,
  sender_id: 111,
  sender_username: null,
  text: "proof attached",
  attachments: [mediaFixture],
  created_at: new Date(0).toISOString(),
} as const satisfies DealMessageOutSchema;

const adminBalanceSnapshotFixture = {
  user_id: 111,
  username: null,
  display_name: "Buyer",
  currency_code: "USDT",
  amount: "10.00000000",
  locked: "0",
  total: "10.00000000",
} as const;

const adminDealDetailFixture = {
  id: 17,
  status: "in_progress",
  description: "Logo design package",
  currency_code: "USDT",
  amount: "100.00000000",
  commission_amount: null,
  commission_paid: false,
  topup_deposit_id: null,
  buyer: adminBalanceSnapshotFixture,
  seller: {
    ...adminBalanceSnapshotFixture,
    user_id: 222,
    display_name: "Seller",
  },
  created_at: new Date(0).toISOString(),
  in_progress_at: null,
  completed_at: null,
  cancellation_initiator: null,
  cancellation_reason: null,
  cancellation_requested_at: null,
  arbitration_initiator: null,
  arbitration_reason: null,
  arbitration_resolved_by_id: null,
  arbitration_resolved_by_username: null,
  arbitration_resolution: null,
  arbitration_resolved_at: null,
  confirm_buyer: false,
  confirm_seller: false,
  events: [],
  messages: [dealMessageFixture],
} as const satisfies AdminDealDetailOutSchema;

const topupResponseFixture = {
  deal: {
    ...dealFixture,
    status: "pending_topup",
    commission_paid: false,
    topup_deposit_id: 501,
    topup_invoice: {
      deposit_id: 501,
      pay_url: "https://pay.example/invoice/501",
      total: 105,
      topup_principal: 100,
      commission: 5,
      paid_total: 0,
      currency_code: "USD",
      provider: "cryptobot",
      expires_at: null,
    },
  },
  invoice: {
    deposit_id: 501,
    pay_url: "https://pay.example/invoice/501",
    total: 105,
    topup_principal: 100,
    commission: 5,
    paid_total: 0,
    currency_code: "USD",
    provider: "cryptobot",
    expires_at: null,
  },
} as const satisfies DealCreateWithTopupOutSchema;

const balanceFundedTopupResponseFixture = {
  deal: {
    ...dealFixture,
    status: "pending_confirmation",
    commission_paid: true,
    topup_deposit_id: null,
    topup_invoice: null,
  },
  invoice: null,
} as const satisfies DealCreateWithTopupOutSchema;

const usdtFixture = {
  id: 1,
  code: "USDT",
  name: "Tether",
  network: "TRC20",
  icon_url: "",
  decimals: 2,
  min_deposit: 1,
  min_withdraw: 1,
  kind: "crypto",
} as const satisfies CurrencyOutSchema;

const walletBalanceFixture = {
  currency: usdtFixture,
  amount: 123.45,
  locked: 0,
  total: 123.45,
  updated_at: null,
  // Audit M-7 — string mirrors of the money fields. See
  // ``WalletBalanceDto`` for the precision rationale.
  amount_str: "123.45",
  locked_str: "0",
  total_str: "123.45",
} as const satisfies WalletBalanceOutSchema;

const serviceFixture = {
  id: 700,
  owner_username: null,
  title: "Logo design",
  description: "Vector logo + brand book",
  price: 250,
  currency: "USD",
  status: "active",
  category: {
    id: 12,
    slug: "design",
    name: "Design",
    icon_key: "palette",
    services_count: 3,
  },
  created_at: null,
  photo_urls: [],
} as const satisfies ServiceOutSchema;

const serviceDetailFixture = {
  ...serviceFixture,
  owner: {
    id: 22,
    username: null,
    display_name: "Deleted owner",
    photo_url: null,
    rating: 0,
    deals_count: 0,
    good: 0,
    bad: 0,
    is_admin: false,
    is_arbiter: false,
  },
  comments_count: 0,
  rating_avg: null,
  rating_count: 0,
} as const satisfies ServiceDetailOutSchema;

const walletDepositFixture = {
  id: 501,
  currency: usdtFixture,
  amount: 100,
  status: "refunded",
  pay_url: "https://pay.example/invoice/501",
  invoice_id: "invoice-501",
  purpose: "wallet",
  provider: "cryptobot",
  created_at: new Date(0).toISOString(),
  paid_at: null,
} as const satisfies WalletDepositOutSchema;

const reviewFixture = {
  id: 601,
  deal_id: null,
  author_username: null,
  target_username: null,
  rating: 5,
  text: "ok",
  created_at: new Date(0).toISOString(),
} as const satisfies ReviewOutSchema;

const supportPersonFixture = {
  id: 44,
  user_id: 44,
  username: null,
  display_name: "Support",
  photo_url: null,
  admin: 1,
  prefix: "admin",
} as const satisfies SupportPersonOutSchema;

const adminUserDetailFixture = {
  id: 111,
  tg_user_id: 111,
  username: null,
  display_name: "Admin view",
  photo_url: null,
  banner_url: null,
  description: "",
  trust_deposit_balance: 0,
  rating_auto: 0,
  rating_manual: null,
  rating_effective: 0,
  good: 0,
  bad: 0,
  deals_total: 0,
  deals_success: 0,
  deals_failed: 0,
  deals_arbitrage: 0,
  deals_sum_override: 0,
  is_admin: false,
  is_arbiter: false,
  is_vip: false,
  is_banned: false,
  ban_reason: null,
  is_frozen: false,
  freeze_reason: null,
  is_anonymous_deals: false,
  is_hidden_profile: false,
  has_pin: false,
  last_ip: null,
  last_login_at: null,
  login_count: 0,
  sessions_count: 0,
  created_at: new Date(0).toISOString(),
} as const satisfies AdminUserDetailOutSchema;

const pinStatusFixture = {
  has_pin: true,
  attempts_left: 5,
  locked_until: null,
  max_attempts: 5,
  session_ttl_seconds: 600,
} as const satisfies PinStatusOutSchema;

// ---------------------------------------------------------------------------
// 2. Compile-time bridge: the fixtures that already passed the
//    OpenAPI shape check must also fit the frontend DTOs the app
//    consumes. If the frontend DTO drifts from the schema, this
//    clause stops compiling too.
// ---------------------------------------------------------------------------

const _meDto: UserCardDto = meFixture;
const _dealDto: DealDto = dealFixture;
const _nullableDealDto: DealDto = nullableDealFixture;
const _mediaDto: MediaDto = mediaFixture;
const _dealMessageDto: DealMessageDto = dealMessageFixture;
const _adminDealDetailDto: AdminDealDetailDto = adminDealDetailFixture;
const _topupResponseDto: DealCreateWithTopupResponseDto = topupResponseFixture;
const _balanceFundedTopupResponseDto: DealCreateWithTopupResponseDto =
  balanceFundedTopupResponseFixture;
const _currencyDto: CurrencyDto = usdtFixture;
const _balanceDto: WalletBalanceDto = walletBalanceFixture;
const _serviceDto: ServiceDto = serviceFixture;
const _serviceDetailDto: ServiceDetailDto = serviceDetailFixture;
const _walletDepositDto: WalletDepositDto = walletDepositFixture;
const _reviewDto: ReviewDto = reviewFixture;
const _supportPersonDto: SupportPersonDto = supportPersonFixture;
const _adminUserDetailDto: AdminUserDetailDto = adminUserDetailFixture;
const _pinDto: PinStatusDto = pinStatusFixture;

// Side-effecting reads so ``unused`` lint rules can't trim the
// compile-time bridge above out of the bundle.
void _meDto;
void _dealDto;
void _nullableDealDto;
void _mediaDto;
void _dealMessageDto;
void _adminDealDetailDto;
void _topupResponseDto;
void _balanceFundedTopupResponseDto;
void _currencyDto;
void _balanceDto;
void _serviceDto;
void _serviceDetailDto;
void _walletDepositDto;
void _reviewDto;
void _supportPersonDto;
void _adminUserDetailDto;
void _pinDto;

// ---------------------------------------------------------------------------
// 3. Runtime sanity checks that surface human-readable failures when
//    the contract changes.
// ---------------------------------------------------------------------------

describe("OpenAPI contract", () => {
  it("exposes a stable info.title so the snapshot can not be repointed by accident", () => {
    expect(openapi.info.title).toBe("Garant TMA");
  });

  it.each([
    "UserOut",
    "AdminUserDetailOut",
    "DealOut",
    "AdminDealDetailOut",
    "DealMessageOut",
    "MediaOut",
    "CurrencyOut",
    "WalletBalanceOut",
    "WalletDepositOut",
    "WalletWithdrawalOut",
    "ServiceOut",
    "ServiceDetailOut",
    "ReviewOut",
    "SupportPersonOut",
    "PinStatusOut",
    "NotificationOut",
    "NotificationCountersOut",
    "TransferStatusOut",
    "TransferConfirmOut",
    "DealCreateWithTopupOut",
    "DealTopupInvoiceOut",
  ])("OpenAPI schema declares %s", (name) => {
    expect(openapi.components.schemas).toHaveProperty(name);
  });

  it("DealOut requires the buyer/seller fields the deal list UI reads", () => {
    const deal = openapi.components.schemas.DealOut as {
      required: readonly string[];
    };
    expect(deal.required).toEqual(
      expect.arrayContaining([
        "id",
        "buyer",
        "seller",
        "amount",
        "description",
        "status",
        "confirm_buyer",
        "confirm_seller",
        "role",
      ]),
    );
  });

  it("CurrencyOut requires decimals so format.ts can pick the right precision", () => {
    const currency = openapi.components.schemas.CurrencyOut as {
      required: readonly string[];
    };
    expect(currency.required).toEqual(
      expect.arrayContaining([
        "id",
        "code",
        "name",
        "decimals",
        "min_deposit",
        "min_withdraw",
      ]),
    );
  });

  it("WalletBalanceOut nests CurrencyOut so the wallet currency page can read decimals", () => {
    const balance = openapi.components.schemas.WalletBalanceOut as {
      properties: Record<string, { $ref?: string }>;
    };
    expect(balance.properties.currency).toEqual({
      $ref: "#/components/schemas/CurrencyOut",
    });
  });
});
