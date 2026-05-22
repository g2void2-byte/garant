import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { UserCardDto } from "@/api/types";

vi.mock("@/lib/tg", () => ({
  getTelegramUser: () => undefined,
}));

import { ProfileHeader } from "./ProfileHeader";

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "me",
    display_name: "Me",
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
    online: true,
    description: "",
    forums: [],
    ...overrides,
  };
}

describe("<ProfileHeader />", () => {
  it("renders 'Пользователь' when prefix is null", () => {
    render(<ProfileHeader user={makeUser()} />);
    expect(screen.getByText("Пользователь")).toBeInTheDocument();
  });

  it("renders the admin label when prefix is 'admin'", () => {
    render(<ProfileHeader user={makeUser({ prefix: "admin" })} />);
    expect(screen.getByText("Админ")).toBeInTheDocument();
  });

  it("renders the arbiter label when prefix is 'arbiter'", () => {
    render(<ProfileHeader user={makeUser({ prefix: "arbiter" })} />);
    expect(screen.getByText("Арбитр")).toBeInTheDocument();
  });

  it("renders the VIP label when prefix is 'vip'", () => {
    render(<ProfileHeader user={makeUser({ prefix: "vip" })} />);
    expect(screen.getByText("VIP")).toBeInTheDocument();
  });
});
