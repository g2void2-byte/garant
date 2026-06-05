import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { UserCardDto } from "@/api/types";

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
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

describe("<ProfileHeader /> user id", () => {
  it("does not render malformed runtime Telegram ids", () => {
    render(<ProfileHeader user={makeUser({ user_id: "1e2" as unknown as number })} />);

    expect(screen.getByText("ID: \u2014")).toBeInTheDocument();
    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
  });

  it("keeps decimal-string runtime Telegram ids canonical", () => {
    render(<ProfileHeader user={makeUser({ user_id: "42" as unknown as number })} />);

    expect(screen.getByText("ID: 42")).toBeInTheDocument();
  });
});
