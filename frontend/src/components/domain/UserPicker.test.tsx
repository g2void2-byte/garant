import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { UserCardDto } from "@/api/types";

const usersSpy = vi.hoisted(() => ({
  calls: [] as Array<{ params: unknown; options: unknown }>,
  data: [] as UserCardDto[],
}));

vi.mock("@/api/hooks", () => ({
  useUsers: (params: unknown, options: unknown) => {
    usersSpy.calls.push({ params, options });
    return { data: usersSpy.data, isLoading: false };
  },
}));

import { UserPicker } from "./UserPicker";

function lastUsersCall() {
  return usersSpy.calls[usersSpy.calls.length - 1];
}

function renderPicker(value: string) {
  return render(
    <MemoryRouter>
      <UserPicker value={value} onChange={vi.fn()} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  usersSpy.calls = [];
  usersSpy.data = [];
});

function makeUser(overrides: Partial<UserCardDto> = {}): UserCardDto {
  return {
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
    ...overrides,
  };
}

describe("<UserPicker />", () => {
  it("does not enable the backend picker query before the user types", () => {
    renderPicker("");

    expect(lastUsersCall()).toEqual({
      params: { picker: true, limit: 8, offset: 0 },
      options: { enabled: false },
    });
  });

  it("limits live-search requests to the visible suggestion count", () => {
    renderPicker("alice");

    expect(lastUsersCall()).toEqual({
      params: { q: "alice", picker: true, limit: 8, offset: 0 },
      options: { enabled: true },
    });
  });

  it("does not pick unsafe username rows when the caller needs a username", async () => {
    usersSpy.data = [makeUser({ username: "../admin", display_name: "Unsafe" })];
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <UserPicker value="unsafe" onChange={onChange} debounceMs={0} />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("textbox"));

    expect(await screen.findByText("Unsafe")).toBeInTheDocument();
    expect(screen.queryByText("@../admin")).not.toBeInTheDocument();
    expect(screen.getByRole("option")).toBeDisabled();
    await user.click(screen.getByRole("option"));
    expect(onChange).not.toHaveBeenCalledWith("../admin");
  });

  it("does not pick a username-less row when the caller needs a username", async () => {
    usersSpy.data = [makeUser({ username: null })];
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <UserPicker value="missing" onChange={onChange} debounceMs={0} />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("textbox", { name: "Контрагент" }));

    expect(await screen.findByText("username не задан")).toBeInTheDocument();
    expect(screen.getByRole("option")).toBeDisabled();
    await user.click(screen.getByRole("option"));
    expect(onChange).not.toHaveBeenCalledWith("null");
  });

  it("renders string ratings in suggestions without crashing", async () => {
    usersSpy.data = [
      makeUser({
        rating: "4.5" as unknown as number,
        reviews_count: 2,
      }),
    ];
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <UserPicker value="alice" onChange={vi.fn()} debounceMs={0} />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("textbox"));

    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("4.5")).toBeInTheDocument();
  });
});
