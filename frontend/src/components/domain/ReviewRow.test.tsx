import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ReviewRow } from "./ReviewRow";
import type { ReviewDto } from "@/api/types";

const baseReview: ReviewDto = {
  id: 1,
  deal_id: 42,
  author_username: "alice",
  target_username: "bob",
  rating: 5,
  text: "ok",
  created_at: "2026-01-01T00:00:00Z",
};

function renderRow(overrides: Partial<ReviewDto> = {}) {
  return render(
    <MemoryRouter>
      <ReviewRow review={{ ...baseReview, ...overrides }} />
    </MemoryRouter>,
  );
}

describe("<ReviewRow />", () => {
  it("links to the author profile when the author username is present", () => {
    renderRow();
    expect(screen.getByRole("link", { name: "от @alice" })).toHaveAttribute(
      "href",
      "/users/alice",
    );
  });

  it("does not turn unsafe author usernames into profile links", () => {
    renderRow({ author_username: "../admin" });
    expect(screen.queryByText("@../admin")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /admin/i })).not.toBeInTheDocument();
  });

  it("renders a fallback without a profile link when the author username is missing", () => {
    renderRow({ author_username: null });
    expect(screen.getByText("автор недоступен")).toBeInTheDocument();
    expect(screen.queryByText("от @null")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /автор/i })).not.toBeInTheDocument();
  });
});
