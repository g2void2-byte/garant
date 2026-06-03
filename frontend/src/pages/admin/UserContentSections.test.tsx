import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  reviewsTotal: 0,
  reviewsLoading: false,
  services: [] as unknown[],
  servicesLoading: false,
  comments: [] as unknown[],
  commentsLoading: false,
  users: [] as UserCardDto[],
  usersLoading: false,
  lastReviewsQuery: undefined as
    | {
        userId: number | undefined;
        direction: "received" | "written";
        page?: number;
        page_size?: number;
      }
    | undefined,
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
  useAdminUserReviews: (
    userId: number | undefined,
    direction: "received" | "written" = "received",
    params: { page?: number; page_size?: number } = {},
  ) => {
    mockState.lastReviewsQuery = { userId, direction, ...params };
    return {
      data: {
        items: mockState.reviews,
        total: mockState.reviewsTotal || mockState.reviews.length,
        page: params.page ?? 1,
        page_size: params.page_size ?? 20,
      },
      isLoading: mockState.reviewsLoading,
    };
  },
  useAdminUserServices: () => ({
    data: {
      items: mockState.services,
      total: mockState.services.length,
      page: 1,
      page_size: 20,
    },
    isLoading: mockState.servicesLoading,
  }),
  useAdminUserComments: () => ({
    data: {
      items: mockState.comments,
      total: mockState.comments.length,
      page: 1,
      page_size: 20,
    },
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

import { CommentsSection, ReviewsSection, ServicesSection } from "./UserContentSections";

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

function makeReview(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    deal_id: null,
    author_id: 7,
    author_username: "buyer1",
    target_id: 42,
    target_username: "seller1",
    rating: 5,
    text: "ok",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeComment(overrides: Record<string, unknown> = {}) {
  return {
    id: 11,
    service_id: 55,
    author_id: 42,
    author_username: "seller1",
    rating: 5,
    text: "nice",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeService(overrides: Record<string, unknown> = {}) {
  return {
    id: 21,
    owner_id: 42,
    category_id: 2,
    category_slug: "design",
    title: "Logo design",
    description: "Service description",
    price: 10,
    status: "active",
    ban_reason: null,
    views: 12,
    deals_count: 3,
    deposit: 0,
    rating_manual: 4.5,
    created_at: "2026-01-01T00:00:00Z",
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

function renderCommentsSection(userId = 42) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CommentsSection userId={userId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderServicesSection(userId = 42) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ServicesSection userId={userId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockState.reviews = [];
  mockState.reviewsTotal = 0;
  mockState.reviewsLoading = false;
  mockState.services = [];
  mockState.servicesLoading = false;
  mockState.comments = [];
  mockState.commentsLoading = false;
  mockState.users = [];
  mockState.usersLoading = false;
  mockState.lastReviewsQuery = undefined;
  mockState.createReview.mutateAsync.mockReset().mockResolvedValue({});
  mockState.updateReview.mutateAsync.mockReset().mockResolvedValue({});
  mockState.deleteReview.mutateAsync.mockReset().mockResolvedValue({});
  mockState.updateService.mutateAsync.mockReset().mockResolvedValue({});
  mockState.deleteService.mutateAsync.mockReset().mockResolvedValue({});
  mockState.updateComment.mutateAsync.mockReset().mockResolvedValue({});
  mockState.deleteComment.mutateAsync.mockReset().mockResolvedValue({});
  toastSpy.mockReset();
});

describe("<ServicesSection />", () => {
  it.each([
    [/Цена/i, "1e2"],
    [/Просмотры/i, "1e2"],
  ])("blocks non-plain numeric service field %s before updating", async (label, value) => {
    const user = userEvent.setup();
    mockState.services = [makeService()];
    const { container } = renderServicesSection(42);

    const edit = container.querySelector("li button[aria-label]") as HTMLButtonElement | null;
    expect(edit).not.toBeNull();
    await user.click(edit!);

    const input = await screen.findByRole("spinbutton", { name: label });
    fireEvent.change(input, { target: { value } });

    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();
    expect(mockState.updateService.mutateAsync).not.toHaveBeenCalled();
  });
});

describe("<CommentsSection />", () => {
  it("blocks rating 0 before updating a comment because the backend accepts 1..5", async () => {
    const user = userEvent.setup();
    mockState.comments = [makeComment()];
    const { container } = renderCommentsSection(42);

    const edit = container.querySelector("button[aria-label]") as HTMLButtonElement | null;
    expect(edit).not.toBeNull();
    await user.click(edit!);
    const ratingInput = await screen.findByRole("spinbutton", { name: /Рейтинг 1\.\.5/i });
    await user.clear(ratingInput);
    await user.type(ratingInput, "0");
    const buttons = screen.getAllByRole("button");
    await user.click(buttons[buttons.length - 1]);

    expect(mockState.updateComment.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "error", title: "Рейтинг 1..5" }),
    );
  });

  it.each(["1.5", "1e0"])(
    "blocks non-integer comment rating %s before updating",
    async (badRating) => {
      const user = userEvent.setup();
      mockState.comments = [makeComment()];
      const { container } = renderCommentsSection(42);

      const edit = container.querySelector("button[aria-label]") as HTMLButtonElement | null;
      expect(edit).not.toBeNull();
      await user.click(edit!);
      const ratingInput = await screen.findByRole("spinbutton", { name: /Рейтинг 1\.\.5/i });
      fireEvent.change(ratingInput, { target: { value: badRating } });
      const buttons = screen.getAllByRole("button");
      await user.click(buttons[buttons.length - 1]);

      expect(mockState.updateComment.mutateAsync).not.toHaveBeenCalled();
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "error", title: "Рейтинг 1..5" }),
      );
    },
  );
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
        name: /Рейтинг 1\.\.5/i,
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

  it("blocks rating 0 before creating a review because the backend accepts 1..5", async () => {
    const user = userEvent.setup();
    mockState.users = [makeUser({ id: 7, username: "buyer1" })];
    renderSection(42);

    await user.click(screen.getByRole("button", { name: /Добавить отзыв/i }));
    await user.type(screen.getByRole("textbox", { name: /^Автор$/ }), "buyer1");
    await user.click(await screen.findByRole("option", { name: /buyer1/i }));
    const ratingInput = screen.getByRole("spinbutton", { name: /Рейтинг 1\.\.5/i });
    await user.clear(ratingInput);
    await user.type(ratingInput, "0");
    const buttons = screen.getAllByRole("button");
    await user.click(buttons[buttons.length - 1]);

    expect(mockState.createReview.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "error", title: "Рейтинг 1..5" }),
    );
  });

  it.each(["1.5", "1e0"])(
    "blocks non-integer rating %s before creating a review",
    async (badRating) => {
      const user = userEvent.setup();
      mockState.users = [makeUser({ id: 7, username: "buyer1" })];
      renderSection(42);

      await user.click(screen.getByRole("button", { name: /Добавить отзыв/i }));
      await user.type(screen.getByRole("textbox", { name: /^Автор$/ }), "buyer1");
      await user.click(await screen.findByRole("option", { name: /buyer1/i }));
      const ratingInput = screen.getByRole("spinbutton", { name: /Рейтинг 1\.\.5/i });
      fireEvent.change(ratingInput, { target: { value: badRating } });
      await user.click(screen.getByRole("button", { name: "Создать" }));

      expect(mockState.createReview.mutateAsync).not.toHaveBeenCalled();
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "error", title: "Рейтинг 1..5" }),
      );
    },
  );

  it("renders missing review usernames as non-handle labels", () => {
    mockState.reviews = [makeReview({ author_username: null, target_username: null })];
    renderSection(42);
    expect(screen.getAllByText(/username \u043d\u0435 \u0437\u0430\u0434\u0430\u043d/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/@\u2014/)).not.toBeInTheDocument();
  });

  it("blocks rating 0 before updating a review because the backend accepts 1..5", async () => {
    const user = userEvent.setup();
    mockState.reviews = [makeReview()];
    const { container } = renderSection(42);

    const edit = container.querySelector("li button[aria-label]") as HTMLButtonElement | null;
    expect(edit).not.toBeNull();
    await user.click(edit!);
    const ratingInput = await screen.findByRole("spinbutton", { name: /Рейтинг 1\.\.5/i });
    await user.clear(ratingInput);
    await user.type(ratingInput, "0");
    const buttons = screen.getAllByRole("button");
    await user.click(buttons[buttons.length - 1]);

    expect(mockState.updateReview.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "error", title: "Рейтинг 1..5" }),
    );
  });

  it.each(["1.5", "1e0"])(
    "blocks non-integer rating %s before updating a review",
    async (badRating) => {
      const user = userEvent.setup();
      mockState.reviews = [makeReview()];
      const { container } = renderSection(42);

      const edit = container.querySelector("li button[aria-label]") as HTMLButtonElement | null;
      expect(edit).not.toBeNull();
      await user.click(edit!);
      const ratingInput = await screen.findByRole("spinbutton", { name: /Рейтинг 1\.\.5/i });
      fireEvent.change(ratingInput, { target: { value: badRating } });
      const buttons = screen.getAllByRole("button");
      await user.click(buttons[buttons.length - 1]);

      expect(mockState.updateReview.mutateAsync).not.toHaveBeenCalled();
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "error", title: "Рейтинг 1..5" }),
      );
    },
  );

  it("requests paged review data and resets the page when direction changes", async () => {
    const user = userEvent.setup();
    mockState.reviews = [makeReview()];
    mockState.reviewsTotal = 45;
    renderSection(42);

    expect(mockState.lastReviewsQuery).toEqual({
      userId: 42,
      direction: "received",
      page: 1,
      page_size: 20,
    });

    await user.click(
      screen.getByRole("button", { name: "\u0412\u043f\u0435\u0440\u0451\u0434" }),
    );

    await waitFor(() => {
      expect(mockState.lastReviewsQuery?.page).toBe(2);
    });

    await user.click(
      screen.getByRole("button", { name: "\u041d\u0430\u043f\u0438\u0441\u0430\u043d\u043e" }),
    );

    await waitFor(() => {
      expect(mockState.lastReviewsQuery).toEqual({
        userId: 42,
        direction: "written",
        page: 1,
        page_size: 20,
      });
    });
  });
});
