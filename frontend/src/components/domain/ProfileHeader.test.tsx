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

  it("renders unknown runtime prefixes as a neutral role label", () => {
    render(<ProfileHeader user={makeUser({ prefix: "moderator" as UserCardDto["prefix"] })} />);
    expect(screen.getByText("Роль неизвестна")).toBeInTheDocument();
    expect(screen.queryByText("moderator")).not.toBeInTheDocument();
  });

  it("renders banner URLs as an image instead of interpolating them into CSS", () => {
    const bannerUrl = "https://cdn.example/a),url(https://evil.example/pixel)";
    const { container } = render(<ProfileHeader user={makeUser({ banner_url: bannerUrl })} />);

    const banner = screen.getByTestId("profile-banner-image");
    expect(banner).toHaveAttribute("src", bannerUrl);
    expect(container.querySelector("[style*='background-image']")).toBeNull();
  });

  it("ignores unsafe banner URLs before rendering an image", () => {
    render(<ProfileHeader user={makeUser({ banner_url: "data:image/svg+xml,<svg onload=alert(1)>" })} />);
    expect(screen.queryByTestId("profile-banner-image")).not.toBeInTheDocument();
  });

  it("renders a username fallback for unsafe username refs", () => {
    render(<ProfileHeader user={makeUser({ username: "../admin" })} />);
    expect(screen.queryByText("@../admin")).not.toBeInTheDocument();
    expect(screen.getByText(/username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d/)).toBeInTheDocument();
  });

  it("renders a username fallback instead of @null", () => {
    render(<ProfileHeader user={makeUser({ username: null })} />);
    expect(screen.getByText("username не задан")).toBeInTheDocument();
    expect(screen.queryByText("@null")).not.toBeInTheDocument();
  });
});
