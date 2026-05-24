import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AdminSettingsDto } from "@/api/types";

/**
 * Tests for `/admin/settings`.
 *
 * Covers loading skeleton, diff-save logic (PATCH only the changed
 * fields), maintenance toggle warning banner, save button disabled
 * when no diff, toast on success/failure, admin guard.
 */

const mockState = vi.hoisted(() => ({
  data: undefined as AdminSettingsDto | undefined,
  loading: false,
  update: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdminSettings: () => ({
    data: mockState.data,
    isLoading: mockState.loading,
  }),
  useAdminUpdateSettings: () => mockState.update,
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  haptic: () => {},
  showBackButton: () => () => {},
}));

import AdminSettingsPage from "./AdminSettingsPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function makeSettings(
  overrides: Partial<AdminSettingsDto> = {},
): AdminSettingsDto {
  return {
    deal_commission_percent: 2,
    vip_commission_percent: -1,
    inactivity_pending_confirmation_days: 7,
    inactivity_pending_cancellation_days: 14,
    pending_topup_expiry_hours: 24,
    max_active_services_per_user: 10,
    maintenance_enabled: false,
    maintenance_message: "Сервис на ТО",
    auto_withdraw_enabled: true,
    ...overrides,
  };
}

beforeEach(() => {
  mockState.data = undefined;
  mockState.loading = false;
  mockState.update = { mutateAsync: vi.fn(), isPending: false };
  mockState.shouldRender = true;
  toastSpy.mockClear();
});

describe("<AdminSettingsPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    renderPage();
    expect(screen.queryByText("Настройки")).not.toBeInTheDocument();
  });

  it("renders skeletons while settings are loading", () => {
    mockState.loading = true;
    const { container } = renderPage();
    expect(container.querySelectorAll(".rounded-card.h-16").length).toBe(6);
  });

  it("renders settings sections with values once data is loaded", () => {
    mockState.data = makeSettings();
    renderPage();
    expect(screen.getByText("Комиссии (%)")).toBeInTheDocument();
    expect(screen.getByText(/Обычная комиссия/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("2")).toBeInTheDocument();
    expect(screen.getAllByDisplayValue("10").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByDisplayValue("Сервис на ТО")).toBeInTheDocument();
  });

  it("'Сохранить' is disabled when there is no diff", () => {
    mockState.data = makeSettings();
    renderPage();
    const save = screen.getByRole("button", { name: /^Сохранить/ });
    expect(save).toBeDisabled();
  });

  it("changing a number field enables save and sends only the diff", async () => {
    mockState.data = makeSettings();
    mockState.update.mutateAsync.mockImplementation(async (patch) => ({
      ...makeSettings(),
      ...(patch as object),
    }));
    const user = userEvent.setup();
    renderPage();
    const dealInput = screen.getByDisplayValue("2") as HTMLInputElement;
    fireEvent.change(dealInput, { target: { value: "3" } });

    const save = screen.getByRole("button", { name: /^Сохранить/ });
    await waitFor(() => expect(save).not.toBeDisabled());
    await user.click(save);
    await waitFor(() =>
      expect(mockState.update.mutateAsync).toHaveBeenCalledWith({
        deal_commission_percent: 3,
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "Сохранено" }),
    );
  });

  it("shows warning banner when maintenance is toggled on (unsaved)", async () => {
    mockState.data = makeSettings({ maintenance_enabled: false });
    const user = userEvent.setup();
    renderPage();
    // Find the maintenance switch — it's the second switch in the page.
    const switches = document.querySelectorAll('button[role="switch"]');
    expect(switches.length).toBeGreaterThanOrEqual(2);
    const maintenanceSwitch = switches[switches.length - 1] as HTMLButtonElement;
    await user.click(maintenanceSwitch);
    expect(
      await screen.findByText(/бот и TMA перестанут принимать любые действия/),
    ).toBeInTheDocument();
  });

  it("save failure surfaces an error toast", async () => {
    mockState.data = makeSettings();
    mockState.update.mutateAsync.mockRejectedValueOnce(new Error("server"));
    const user = userEvent.setup();
    renderPage();

    const dealInput = screen.getByDisplayValue("2") as HTMLInputElement;
    fireEvent.change(dealInput, { target: { value: "4" } });
    await user.click(screen.getByRole("button", { name: /^Сохранить/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          title: "Ошибка",
          body: "server",
        }),
      ),
    );
  });
});
