import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import type { CategoryDto } from "@/api/types";

const mockState = vi.hoisted(() => ({
  categories: [] as CategoryDto[],
  createService: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  uploadMedia: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

vi.mock("@/api/hooks", () => ({
  useCategories: () => ({ data: mockState.categories, isLoading: false }),
  useCreateService: () => mockState.createService,
  useUploadMedia: () => mockState.uploadMedia,
}));

const hapticSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  haptic: hapticSpy,
  showBackButton: () => () => {},
  useTelegramViewport: () => null,
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

import AddServicePage from "./AddServicePage";

function renderPage() {
  return render(
    <MemoryRouter>
      <AddServicePage />
    </MemoryRouter>,
  );
}

async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Выберите категорию/i }));
  await user.click(screen.getByRole("button", { name: "Design" }));
  await user.type(screen.getByLabelText(/Название/i), "Logo design");
}

beforeEach(() => {
  mockState.categories = [
    {
      id: 1,
      slug: "design",
      name: "Design",
      icon_key: "paintbrush",
      services_count: 0,
    },
  ];
  mockState.createService.mutateAsync.mockReset().mockResolvedValue({});
  mockState.createService.isPending = false;
  mockState.uploadMedia.mutateAsync.mockReset().mockResolvedValue({ url: "/media/service/1.png" });
  mockState.uploadMedia.isPending = false;
  hapticSpy.mockClear();
  toastSpy.mockReset();
});

describe("<AddServicePage />", () => {
  it.each(["1e2", "1e-2"])("blocks non-plain service price %s", async (badPrice) => {
    const user = userEvent.setup();
    renderPage();

    await fillRequiredFields(user);
    fireEvent.change(screen.getByLabelText(/Цена \(USDT\)/i), {
      target: { value: badPrice },
    });
    await user.click(screen.getByRole("button", { name: /Создать услугу/i }));

    expect(mockState.createService.mutateAsync).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "error", title: "Введите корректную цену" }),
    );
    expect(hapticSpy).toHaveBeenCalledWith("error");
  });

  it("submits plain decimal prices as exact strings", async () => {
    const user = userEvent.setup();
    renderPage();

    await fillRequiredFields(user);
    await user.type(screen.getByLabelText(/Описание/i), "Clean vector logo");
    fireEvent.change(screen.getByLabelText(/Цена \(USDT\)/i), {
      target: { value: "0.123456789123456789" },
    });
    await user.click(screen.getByRole("button", { name: /Создать услугу/i }));

    await waitFor(() => {
      expect(mockState.createService.mutateAsync).toHaveBeenCalledTimes(1);
    });
    expect(mockState.createService.mutateAsync).toHaveBeenCalledWith({
      category_slug: "design",
      title: "Logo design",
      description: "Clean vector logo",
      price: "0.123456789123456789",
      photo_urls: [],
    });
    expect(hapticSpy).toHaveBeenCalledWith("success");
  });

  it("keeps unsafe uploaded service photo URLs out of previews and submits", async () => {
    const user = userEvent.setup();
    mockState.uploadMedia.mutateAsync
      .mockResolvedValueOnce({ url: "/media/service/ok.png" })
      .mockResolvedValueOnce({ url: "javascript:alert(1)" });
    const { container } = renderPage();

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, [
      new File(["ok"], "ok.png", { type: "image/png" }),
      new File(["bad"], "bad.png", { type: "image/png" }),
    ]);

    await waitFor(() => expect(mockState.uploadMedia.mutateAsync).toHaveBeenCalledTimes(2));
    const previews = Array.from(container.querySelectorAll("img"));
    expect(previews).toHaveLength(1);
    expect(previews[0].getAttribute("src")).toBe("/media/service/ok.png");
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "error",
        title: "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u0430\u044f \u0441\u0441\u044b\u043b\u043a\u0430 \u043d\u0430 \u0444\u043e\u0442\u043e",
      }),
    );

    await fillRequiredFields(user);
    const buttons = screen.getAllByRole("button");
    await user.click(buttons[buttons.length - 1]);

    await waitFor(() => {
      expect(mockState.createService.mutateAsync).toHaveBeenCalledTimes(1);
    });
    expect(mockState.createService.mutateAsync).toHaveBeenCalledWith(
      expect.objectContaining({ photo_urls: ["/media/service/ok.png"] }),
    );
  });
});
