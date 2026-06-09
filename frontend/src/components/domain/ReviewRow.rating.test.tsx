import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
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

function renderRow(rating: ReviewDto["rating"]) {
  return render(
    <MemoryRouter>
      <ReviewRow review={{ ...baseReview, rating }} />
    </MemoryRouter>,
  );
}

function filledStarCount(container: HTMLElement): number {
  return container.querySelectorAll('svg[fill="currentColor"]').length;
}

describe("<ReviewRow /> rating stars", () => {
  it("renders decimal-string ratings through the shared rating parser", () => {
    const { container } = renderRow("4.5" as unknown as number);

    expect(filledStarCount(container)).toBe(5);
  });

  it.each(["1e1", "0x5", "6", "not-a-rating"])(
    "does not coerce malformed runtime rating %s into filled stars",
    (rating) => {
      const { container } = renderRow(rating as unknown as number);

      expect(filledStarCount(container)).toBe(0);
    },
  );
});
