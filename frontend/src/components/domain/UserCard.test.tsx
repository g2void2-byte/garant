import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { UserCard } from "./UserCard";
import type { UserCardDto } from "@/api/types";

const baseUser: UserCardDto = {
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
  rating: 5,
  reviews_count: 1,
  deals_count: 2,
  deals_success: 2,
  deals_failed: 0,
  deals_arbitrage: 0,
  deals_sum: 100,
  online: true,
  description: "",
  forums: [],
};

function renderCard(overrides: Partial<UserCardDto> = {}) {
  return render(
    <MemoryRouter>
      <UserCard user={{ ...baseUser, ...overrides }} />
    </MemoryRouter>,
  );
}

describe("<UserCard />", () => {
  it("links to the user profile when username is present", () => {
    renderCard();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/users/alice");
  });

  it("does not build a /users/null link when username is missing", () => {
    renderCard({ username: null });
    expect(screen.getByText("username не задан")).toBeInTheDocument();
    expect(screen.queryByText("@null")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
