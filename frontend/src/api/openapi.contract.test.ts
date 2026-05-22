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
 *     (UserCard / Deal / WalletBalance / Currency / PinStatus)
 *   - frontend ``UserCardDto`` / ``DealDto`` / etc. align with their
 *     OpenAPI counterparts on the fields the UI reads
 */

import { describe, expect, it } from "vitest";
import openapi from "../../openapi.json";
import type { components } from "./openapi.generated";
import type {
  CurrencyDto,
  DealDto,
  PinStatusDto,
  UserCardDto,
  WalletBalanceDto,
} from "./types";

type Schemas = components["schemas"];
type DealOutSchema = Schemas["DealOut"];
type CurrencyOutSchema = Schemas["CurrencyOut"];
type WalletBalanceOutSchema = Schemas["WalletBalanceOut"];
type PinStatusOutSchema = Schemas["PinStatusOut"];
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
  username: "testbuyer",
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
  pay_comission: "buyer",
  pay_commission: "buyer",
  status: "in_progress",
  confirm_buyer: false,
  confirm_seller: false,
  role: "buyer",
  created_at: new Date(0).toISOString(),
  currency_code: "USDT",
  amount: 100,
  commission_amount: 5,
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
} as const satisfies WalletBalanceOutSchema;

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
const _currencyDto: CurrencyDto = usdtFixture;
const _balanceDto: WalletBalanceDto = walletBalanceFixture;
const _pinDto: PinStatusDto = pinStatusFixture;

// Side-effecting reads so ``unused`` lint rules can't trim the
// compile-time bridge above out of the bundle.
void _meDto;
void _dealDto;
void _currencyDto;
void _balanceDto;
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
    "DealOut",
    "CurrencyOut",
    "WalletBalanceOut",
    "WalletDepositOut",
    "WalletWithdrawalOut",
    "PinStatusOut",
    "NotificationOut",
    "NotificationCountersOut",
    "TransferStatusOut",
    "TransferConfirmOut",
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
        "pay_comission",
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
