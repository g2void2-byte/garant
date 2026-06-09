import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { UserCardDto } from "@/api/types";

const mockState = vi.hoisted(() => ({
  me: undefined as UserCardDto | undefined,
  updateMe: {
    mutateAsync: vi.fn(),
    isPending: false,
  },
  uploadMedia: {
    mutateAsync: vi.fn(),
    isPending: false,
  },
}));

const toastSpy = vi.hoisted(() => vi.fn());
const hapticSpy = vi.hoisted(() => vi.fn());

vi.mock("@/api/hooks", () => ({
  useMe: () => ({ data: mockState.me, isLoading: false }),
  useUpdateMe: () => mockState.updateMe,
  useUploadMedia: () => mockState.uploadMedia,
  useCurrencies: () => ({ data: [] }),
}));

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  haptic: hapticSpy,
  showBackButton: () => () => {},
}));

vi.mock("@/components/BannerCropModal", () => ({
  BannerCropModal: ({
    open,
    onApply,
  }: {
    open: boolean;
    onApply: (file: File) => void | Promise<void>;
  }) =>
    open ? (
      <button
        type="button"
        onClick={() =>
          onApply(new File(["cropped"], "banner.jpg", { type: "image/jpeg" }))
        }
      >
        apply banner crop
      </button>
    ) : null,
}));

import SettingsPage from "./SettingsPage";

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
    reviews_count: 0,
    deals_count: 0,
    deals_success: 0,
    deals_failed: 0,
    deals_arbitrage: 0,
    deals_sum: 0,
    online: true,
    banner_url: null,
    description: "",
    forums: [],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockState.me = makeUser();
  mockState.updateMe = {
    mutateAsync: vi.fn().mockResolvedValue(makeUser()),
    isPending: false,
  };
  mockState.uploadMedia = {
    mutateAsync: vi.fn().mockResolvedValue({
      id: 1,
      kind: "banner",
      url: "/media/banner/current.jpg",
      name: "current.jpg",
      size: 1,
      content_type: "image/jpeg",
      created_at: null,
    }),
    isPending: false,
  };
  toastSpy.mockClear();
  hapticSpy.mockClear();
});

describe("<SettingsPage />", () => {
  it("normalizes uploaded banner media URLs before updating the profile", async () => {
    const user = userEvent.setup();
    mockState.uploadMedia.mutateAsync.mockResolvedValue({
      id: 1,
      kind: "banner",
      url: " /media/banner/ok.jpg?exp=1&sig=abc ",
      name: "ok.jpg",
      size: 1,
      content_type: "image/jpeg",
      created_at: null,
    });
    const { container } = renderPage();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["raw"], "raw.jpg", { type: "image/jpeg" }));
    await user.click(screen.getByRole("button", { name: /apply banner crop/i }));

    await waitFor(() =>
      expect(mockState.updateMe.mutateAsync).toHaveBeenCalledWith({
        banner_url: "/media/banner/ok.jpg?exp=1&sig=abc",
      }),
    );
    expect(mockState.updateMe.mutateAsync).not.toHaveBeenCalledWith({
      banner_url: " /media/banner/ok.jpg?exp=1&sig=abc ",
    });
  });

  it("rejects malformed uploaded banner URLs before profile updates", async () => {
    const user = userEvent.setup();
    mockState.uploadMedia.mutateAsync.mockResolvedValue({
      id: 1,
      kind: "banner",
      url: "javascript:alert(1)",
      name: "bad.jpg",
      size: 1,
      content_type: "image/jpeg",
      created_at: null,
    });
    const { container } = renderPage();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["raw"], "raw.jpg", { type: "image/jpeg" }));
    await user.click(screen.getByRole("button", { name: /apply banner crop/i }));

    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith({
        kind: "error",
        title: "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u0430\u044f \u0441\u0441\u044b\u043b\u043a\u0430 \u043d\u0430 \u0431\u0430\u043d\u043d\u0435\u0440",
      }),
    );
    expect(mockState.updateMe.mutateAsync).not.toHaveBeenCalled();
  });
});
