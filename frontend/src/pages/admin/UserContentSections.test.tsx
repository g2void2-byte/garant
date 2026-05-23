import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UserCardDto } from "@/api/types";

/**
 * Tests for the admin "edit on behalf of user" content sections.
 *
 * Currently focuses on ``ReviewsSection`` → "Новый отзыв" sheet,
 * which switched from a free-text "@username" input + secondary
 * ``GET /api/admin/users?q=…`` lookup to the live-search ``UserPicker``.
 * The picker resolves the author into a full ``UserCardDto`` up-front,
 * so the submitted payload carries the picked ``author_id`` directly
 * (no fallback handle resolution).
 */

const mockState = vi.hoisted(() => ({
  reviews: [] as unknown[],
  reviewsLoading: false,
  services: [] as unknown[],
  servicesLoading: false,
  comments: [] as unknown[],
  commentsLoading: false,
  users: [] as UserCardDto[],
  usersLoading: false,
  createReview: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  updateReview: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  deleteReview: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  deleteService: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  updateService: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  updateComment: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  deleteComment: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminUserReviews: () => ({
    data: mockState.reviews,
    isLoading: mockState.reviewsLoading,
  }),
  useAdminUserServices: () => ({
    data: mockState.services,
    isLoading: mockState.servicesLoading,
  }),
  useAdminUserComments: () => ({
    data: mockState.comments,
    isLoading: mockState.commentsLoading,
  }),
  useAdminCreateReview: () => mockState.createReview,
  useAdminUpdateReview: () => mockState.updateReview,
  useAdminDeleteReview: () => mockState.deleteReview,
  useAdminDeleteService: () => mockState.deleteService,
  useAdminUpdateService: () => mockState.updateService,
  useAdminUpdateComment: () => mockState.updateComment,
  useAdminDeleteComment: () => mockState.deleteComment,
}));

vi.mock("@/api/hooks", () => ({
  useUsers: () => ({ data: mockState.users, isLoading: mockState.usersLoading }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
  ToastProvider: ({ children }: { children: React.ReactNode }) => children,
}));

import { ReviewsSection } from "./UserContentSections";

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "buyer1",
    display_name: "Buyer One",
    photo_url: null,
    admin: 0,
    prefix: null,
    good: 0,
    bad: 0,
    deposit: 0,
    rating: 4.5,
    reviews_count: 8,
    deals_count: 12,
    deals_success: 12,
    deals_failed: 0,
    deals_arbitrage: 0,
    deals_sum: 100,
    online: true,
    description: "",
    forums: [],
    ...overrides,
  };
}

function renderSection(userId = 42) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ReviewsSection userId={userId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockState.reviews = [];
  mockState.reviewsLoading = false;
  mockState.users = [];
  mockState.usersLoading = false;
  mockState.createReview.mutateAsync.mockReset().mockResolvedValue({});
  toastSpy.mockReset();
});

describe("<ReviewsSection /> · Новый отзыв sheet", () => {
  it("opens the sheet with a UserPicker for the author", async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(screen.getByRole("button", { name: /Добавить отзыв/i }));

    // The new sheet uses the live-search UserPicker labelled "Автор",
    // not the legacy "Автор (@username)" plain input.
    expect(
      screen.getByRole("textbox", { name: /^Автор$/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Автор (@username)"),
    ).not.toBeInTheDocument();
  });

  it("blocks submit and toasts when no author is picked", async () => {
    const user = userEvent.setup();
    renderSection(42);

    await user.click(screen.getByRole("button", { name: /Добавить отзыв/i }));

    // Type into the search input but never tap a suggestion — the
    // submit MUST refuse because no UserCardDto was resolved.
    await user.type(
      screen.getByRole("textbox", { name: /^Автор$/ }),
      "buyer1",
    );

    await user.click(screen.getByRole("button", { name: "Создать" }));

    expect(mockState.createReview.mutateAsync).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ title: "Выберите автора" }),
      );
    });
  });

  it(
    "submits with the picked author_id (no secondary username lookup)",
    async () => {
      const user = userEvent.setup();
      mockState.users = [makeUser({ id: 7, username: "buyer1" })];
      renderSection(42);

      await user.click(
        screen.getByRole("button", { name: /Добавить отзыв/i }),
      );

      // Type → pick the matching row in the dropdown.
      await user.type(
        screen.getByRole("textbox", { name: /^Автор$/ }),
        "buyer1",
      );
      const option = await screen.findByRole("option", {
        name: /buyer1/i,
      });
      await user.click(option);

      // Fill the remaining fields and submit.
      const ratingInput = screen.getByRole("spinbutton", {
        name: /Рейтинг 0\.\.5/i,
      });
      await user.clear(ratingInput);
      await user.type(ratingInput, "4");

      const textArea = screen.getByRole("textbox", { name: /^Текст$/ });
      await user.type(textArea, "Хороший контрагент");

      await user.click(screen.getByRole("button", { name: "Создать" }));

      await waitFor(() => {
        expect(mockState.createReview.mutateAsync).toHaveBeenCalledTimes(1);
      });
      expect(mockState.createReview.mutateAsync).toHaveBeenCalledWith({
        author_id: 7,
        target_id: 42,
        rating: 4,
        text: "Хороший контрагент",
      });
    },
  );
});
