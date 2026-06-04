import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import type { UserCardDto, WalletBalanceDto } from "@/api/types";
import { ProfileFiatBalanceCard } from "./ProfileFiatBalanceCard";

const mockState = vi.hoisted(() => ({
  balances: [] as WalletBalanceDto[],
  isLoading: false,
}));

vi.mock("@/api/hooks", () => ({
  useWalletBalances: () => ({ data: mockState.balances, isLoading: mockState.isLoading }),
}));

function makeUser(over: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "alice",
    display_name: "Alice",
    photo_url: null,
    admin: 0,
    prefix: null,
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
    online: false,
    description: "",
    forums: [],
    ...over,
  };
}

function makeBalance(code = "USD"): WalletBalanceDto {
  return {
    currency: {
      id: 1,
      code,
      name: code,
      network: "",
      icon_url: "",
      decimals: 2,
      min_deposit: 1,
      min_withdraw: 1,
      kind: "fiat",
    },
    amount: 10,
    locked: 0,
    total: 10,
    updated_at: null,
    amount_str: "10",
    locked_str: "0",
    total_str: "10",
  };
}

function LocationProbe() {
  const loc = useLocation();
  return <span data-testid="location">{loc.pathname + loc.search}</span>;
}

function renderCard(user: UserCardDto) {
  return render(
    <MemoryRouter initialEntries={["/profile"]}>
      <ProfileFiatBalanceCard user={user} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockState.balances = [makeBalance("USD"), makeBalance("UAH")];
  mockState.isLoading = false;
});

describe("<ProfileFiatBalanceCard />", () => {
  it("falls back to USD when the preferred display currency is malformed", async () => {
    const user = userEvent.setup();
    renderCard(makeUser({ display_currency_code: "USD&provider=x" }));

    await user.click(screen.getAllByRole("button")[0]);
    expect(screen.getByTestId("location").textContent).toBe("/wallet/deposit?currency=USD");
  });

  it("normalizes valid preferred currency codes before wallet navigation", async () => {
    const user = userEvent.setup();
    renderCard(makeUser({ display_currency_code: " uah " }));

    await user.click(screen.getAllByRole("button")[1]);
    expect(screen.getByTestId("location").textContent).toBe("/wallet/withdraw?currency=UAH");
  });
});
