import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const usersSpy = vi.hoisted(() => ({
  calls: [] as Array<{ params: unknown; options: unknown }>,
}));

vi.mock("@/api/hooks", () => ({
  useUsers: (params: unknown, options: unknown) => {
    usersSpy.calls.push({ params, options });
    return { data: [], isLoading: false };
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
});

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
});
