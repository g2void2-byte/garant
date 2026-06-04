import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { UserCardDto } from "@/api/types";
import { ProfileStatsGrid } from "./ProfileStatsGrid";

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

describe("<ProfileStatsGrid />", () => {
  it("shows '—' when there are no reviews and no rating", () => {
    render(<ProfileStatsGrid user={makeUser()} />);
    // The rating tile renders "—" alongside the "Рейтинг" label.
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows the admin-set rating even when reviews_count is 0", () => {
    // This is the bug fix for issue #10 — a manually-set rating
    // used to be hidden behind ``reviews_count > 0``.
    render(<ProfileStatsGrid user={makeUser({ rating: 4.5, reviews_count: 0 })} />);
    expect(screen.getByText("4.5")).toBeInTheDocument();
    // No "(0)" suffix — the review count gate is preserved.
    expect(screen.queryByText(/\(0\)/)).not.toBeInTheDocument();
  });

  it("shows decimal-string ratings through the shared rating parser", () => {
    render(<ProfileStatsGrid user={makeUser({ rating: "4.25" as unknown as number, reviews_count: 0 })} />);
    expect(screen.getByText("4.3")).toBeInTheDocument();
  });

  it("does not coerce malformed rating strings into display ratings", () => {
    render(
      <ProfileStatsGrid
        user={makeUser({ rating: "0x5" as unknown as number, reviews_count: 0 })}
      />,
    );
    expect(screen.queryByText("5.0")).not.toBeInTheDocument();
  });

  it("shows 'rating (count)' once at least one review exists", () => {
    render(<ProfileStatsGrid user={makeUser({ rating: 4.2, reviews_count: 12 })} />);
    expect(screen.getByText("4.2 (12)")).toBeInTheDocument();
  });

  it("renders the success / failed / arbitrage breakdown tiles (item 11)", () => {
    render(
      <ProfileStatsGrid
        user={makeUser({
          deals_count: 18,
          deals_success: 12,
          deals_failed: 4,
          deals_arbitrage: 2,
        })}
      />,
    );
    expect(screen.getByText("Успешных")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Неуспешных")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("Арбитражи")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders neutral values for malformed activity counters", () => {
    render(
      <ProfileStatsGrid
        user={makeUser({
          deals_count: "1e2" as unknown as number,
          deals_success: "0x10" as unknown as number,
          deals_failed: -1,
          deals_arbitrage: Number.NaN,
          rating: "4.5" as unknown as number,
          reviews_count: "1e2" as unknown as number,
        })}
      />,
    );

    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0x10/)).not.toBeInTheDocument();
    expect(screen.queryByText("4.5 (1e2)")).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
  });
});
