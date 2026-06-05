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

describe("<ReviewRow /> deal links", () => {
  it("does not build deal links from malformed runtime deal ids", () => {
    renderRow({ deal_id: "0x2a" as unknown as number });

    expect(screen.queryByText(/0x2a/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /0x2a/ })).not.toBeInTheDocument();
  });

  it("uses canonical deal links for decimal-string runtime deal ids", () => {
    renderRow({ deal_id: "42" as unknown as number });

    expect(screen.getByRole("link", { name: /#42/ })).toHaveAttribute("href", "/deals/42");
  });
});
