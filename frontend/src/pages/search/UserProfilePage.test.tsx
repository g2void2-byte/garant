import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReviewDto, ServiceDto, UserCardDto } from "@/api/types";

const meState = vi.hoisted(() => ({ data: undefined as UserCardDto | undefined }));
const userState = vi.hoisted(() => ({
  data: undefined as UserCardDto | undefined,
  isLoading: false,
}));
const servicesState = vi.hoisted(() => ({ data: undefined as ServiceDto[] | undefined }));
const reviewsState = vi.hoisted(() => ({ data: undefined as ReviewDto[] | undefined }));

vi.mock("@/api/hooks", () => ({
  useMe: () => meState,
  useUser: () => userState,
  useServices: () => servicesState,
  useReviews: () => reviewsState,
}));

vi.mock("@/lib/tg", () => ({
  openTelegramLink: vi.fn(),
  openExternalLink: vi.fn(),
  showBackButton: () => () => {},
  haptic: vi.fn(),
  getTelegramUser: () => undefined,
}));

import UserProfilePage from "./UserProfilePage";

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
    id: 1,
    user_id: 1,
    username: "alice",
    display_name: "Alice",
    photo_url: null,
    admin: 0,
    prefix: null,
    good: 5,
    bad: 0,
    deposit: 0,
    rating: 5,
    reviews_count: 0,
    deals_count: 10,
    deals_sum: 1000,
    online: true,
    description: "",
    forums: [],
    ...overrides,
  };
}

function renderAt(username: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/u/${username}`]}>
        <Routes>
          <Route path="/u/:username" element={<UserProfilePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  meState.data = makeUser({ id: 99, user_id: 99, username: "me" });
  userState.data = undefined;
  userState.isLoading = false;
  servicesState.data = undefined;
  reviewsState.data = undefined;
});

describe("<UserProfilePage />", () => {
  it("renders skeletons while the user is loading", () => {
    userState.isLoading = true;
    const { container } = renderAt("alice");
    expect(container.querySelectorAll(".shimmer").length).toBeGreaterThan(0);
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
  });

  it("renders the profile, action buttons and empty service list for another user", () => {
    userState.data = makeUser({ username: "alice", display_name: "Alice" });
    servicesState.data = [];
    reviewsState.data = [];
    renderAt("alice");
    expect(screen.getAllByText(/Alice/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Сделка/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Написать/i })).toBeInTheDocument();
    expect(screen.getByText("Услуги отсутствуют")).toBeInTheDocument();
  });

  it("hides 'Сделка/Написать' actions when viewing one's own profile", () => {
    meState.data = makeUser({ username: "alice" });
    userState.data = makeUser({ username: "alice" });
    servicesState.data = [];
    reviewsState.data = [];
    renderAt("alice");
    expect(screen.queryByRole("button", { name: /Сделка/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Написать/i })).not.toBeInTheDocument();
  });

  it("renders the empty reviews state when the reviews tab has no data", () => {
    userState.data = makeUser({ username: "alice" });
    servicesState.data = [];
    reviewsState.data = [];
    renderAt("alice");
    expect(screen.getByText("Услуги отсутствуют")).toBeInTheDocument();
  });
});
