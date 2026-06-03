import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AdminCategoryDto,
  AdminCurrencyDto,
} from "@/api/types";

/**
 * Tests for `/admin/taxonomy` (categories + currencies tabs).
 *
 * Covers tab switching, list rendering (with off badge), category
 * delete with confirm, category upsert form (slug+name gating, edit
 * mode disables slug), currency upsert form (code uppercases, edit
 * mode disables code), admin guard.
 */

const mockState = vi.hoisted(() => ({
  categories: undefined as AdminCategoryDto[] | undefined,
  currencies: undefined as AdminCurrencyDto[] | undefined,
  catLoading: false,
  curLoading: false,
  delCategory: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  delCurrency: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  upsertCategory: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  upsertCurrency: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminCategories: () => ({
    data: mockState.categories,
    isLoading: mockState.catLoading,
  }),
  useAdminCurrencies: () => ({
    data: mockState.currencies,
    isLoading: mockState.curLoading,
  }),
  useAdminDeleteCategory: () => mockState.delCategory,
  useAdminDeleteCurrency: () => mockState.delCurrency,
  useAdminUpsertCategory: () => mockState.upsertCategory,
  useAdminUpsertCurrency: () => mockState.upsertCurrency,
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
  showBackButton: () => () => {},
  // L-15 — ``confirmDialog`` reads ``tg.showConfirm``; ``undefined``
  // forces the fallback through ``window.confirm`` so the existing
  // ``vi.spyOn(window, "confirm")`` mocks below keep working.
  tg: undefined,
}));

import AdminTaxonomyPage from "./AdminTaxonomyPage";

function renderPage(initialEntry: string = "/admin/taxonomy") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <AdminTaxonomyPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeCategory(
  overrides: Partial<AdminCategoryDto> = {},
): AdminCategoryDto {
  return {
    id: 1,
    slug: "games",
    name: "Games",
    icon: "🎮",
    ...overrides,
  };
}

function makeCurrency(
  overrides: Partial<AdminCurrencyDto> = {},
): AdminCurrencyDto {
  return {
    id: 2,
    code: "USDT",
    name: "Tether",
    network: "TRC20",
    icon_url: "",
    decimals: 2,
    min_deposit: 5,
    min_withdraw: 10,
    is_active: true,
    sort_order: 0,
    ...overrides,
  };
}

beforeEach(() => {
  mockState.categories = undefined;
  mockState.currencies = undefined;
  mockState.catLoading = false;
  mockState.curLoading = false;
  mockState.delCategory = { mutateAsync: vi.fn(), isPending: false };
  mockState.delCurrency = { mutateAsync: vi.fn(), isPending: false };
  mockState.upsertCategory = { mutateAsync: vi.fn(), isPending: false };
  mockState.upsertCurrency = { mutateAsync: vi.fn(), isPending: false };
  mockState.shouldRender = true;
  toastSpy.mockClear();
});

describe("<AdminTaxonomyPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Таксономия")).not.toBeInTheDocument();
  });

  it("renders categories tab by default", () => {
    mockState.categories = [makeCategory()];
    renderPage();
    expect(screen.getByText("Games")).toBeInTheDocument();
    expect(screen.getByText("games")).toBeInTheDocument();
  });

  it("switches to currencies tab when its chip is clicked", async () => {
    mockState.categories = [makeCategory()];
    mockState.currencies = [makeCurrency({ is_active: false })];
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Валюты/ }));
    expect(screen.getByText("USDT")).toBeInTheDocument();
    expect(screen.getByText("off")).toBeInTheDocument();
    expect(screen.getByText(/Tether · TRC20/)).toBeInTheDocument();
  });

  it("renders the currencies pane directly when URL has ?tab=currencies", () => {
    mockState.categories = [makeCategory()];
    mockState.currencies = [makeCurrency()];
    renderPage("/admin/taxonomy?tab=currencies");
    // The currencies row should be present without any tab clicks.
    expect(screen.getByText("USDT")).toBeInTheDocument();
    // The categories row should NOT be present.
    expect(screen.queryByText("Games")).not.toBeInTheDocument();
  });

  it("shows empty-state copy when categories list is empty", () => {
    mockState.categories = [];
    renderPage();
    expect(screen.getByText("Категорий нет")).toBeInTheDocument();
  });

  it("shows empty-state copy when currencies list is empty", async () => {
    mockState.categories = [makeCategory()];
    mockState.currencies = [];
    renderPage("/admin/taxonomy?tab=currencies");
    expect(screen.getByText("Валют нет")).toBeInTheDocument();
  });

  it("category delete with confirm fires mutation and toasts", async () => {
    mockState.categories = [makeCategory()];
    mockState.delCategory.mutateAsync.mockResolvedValue({});
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByText("×"));
    await waitFor(() =>
      expect(mockState.delCategory.mutateAsync).toHaveBeenCalledWith(1),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "info", title: "Удалено" }),
    );
    confirmSpy.mockRestore();
  });

  it("currency delete with confirm fires mutation and toasts", async () => {
    mockState.categories = [makeCategory()];
    mockState.currencies = [makeCurrency()];
    mockState.delCurrency.mutateAsync.mockResolvedValue({});
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderPage("/admin/taxonomy?tab=currencies");

    await user.click(screen.getByText("Г—"));
    await waitFor(() =>
      expect(mockState.delCurrency.mutateAsync).toHaveBeenCalledWith(2),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "info", title: "РЈРґР°Р»РµРЅРѕ" }),
    );
    confirmSpy.mockRestore();
  });

  it("category 'Добавить' opens an empty new-category form", async () => {
    mockState.categories = [];
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Добавить/ }));
    expect(await screen.findByText("Новая категория")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();
  });

  it("category save calls upsert with slug+name+icon, toasts success", async () => {
    mockState.categories = [];
    mockState.upsertCategory.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Добавить/ }));
    const inputs = await screen.findAllByRole("textbox");
    fireEvent.change(inputs[0], { target: { value: "games" } });
    fireEvent.change(inputs[1], { target: { value: "Games" } });
    fireEvent.change(inputs[2], { target: { value: "🎮" } });
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(mockState.upsertCategory.mutateAsync).toHaveBeenCalledWith({
        slug: "games",
        name: "Games",
        icon: "🎮",
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Сохранено" }),
    );
  });

  it("currency 'Добавить' opens new-currency form; code uppercases", async () => {
    mockState.categories = [];
    mockState.currencies = [];
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Валюты/ }));
    await user.click(screen.getByRole("button", { name: /Добавить/ }));

    const codeInput = (await screen.findAllByRole("textbox"))[0];
    fireEvent.change(codeInput, { target: { value: "btc" } });
    expect((codeInput as HTMLInputElement).value).toBe("BTC");
  });

  it("blocks ambiguous currency numeric fields", async () => {
    mockState.categories = [];
    mockState.currencies = [];
    const user = userEvent.setup();
    renderPage("/admin/taxonomy?tab=currencies");
    await user.click(screen.getByRole("button", { name: /Добавить/ }));

    const inputs = await screen.findAllByRole("textbox");
    fireEvent.change(inputs[0], { target: { value: "btc" } });
    fireEvent.change(inputs[3], { target: { value: "1e2" } });

    expect(screen.getByText("Введите целое число 0..8")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
    expect(mockState.upsertCurrency.mutateAsync).not.toHaveBeenCalled();
  });

  it("currency save sends parsed decimal values", async () => {
    mockState.categories = [];
    mockState.currencies = [];
    mockState.upsertCurrency.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage("/admin/taxonomy?tab=currencies");
    await user.click(screen.getByRole("button", { name: /Добавить/ }));

    const inputs = await screen.findAllByRole("textbox");
    fireEvent.change(inputs[0], { target: { value: "btc" } });
    fireEvent.change(inputs[1], { target: { value: " Bitcoin " } });
    fireEvent.change(inputs[2], { target: { value: " mainnet " } });
    fireEvent.change(inputs[3], { target: { value: "8" } });
    fireEvent.change(inputs[4], { target: { value: ".5" } });
    fireEvent.change(inputs[5], { target: { value: "0" } });

    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() =>
      expect(mockState.upsertCurrency.mutateAsync).toHaveBeenCalledWith({
        code: "BTC",
        name: "Bitcoin",
        network: "mainnet",
        decimals: 8,
        min_deposit: 0.5,
        min_withdraw: 0,
        is_active: true,
      }),
    );
  });
});
