import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGetSpy = vi.hoisted(() => vi.fn());
const apiPostSpy = vi.hoisted(() => vi.fn());
const toastSpy = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", () => ({
  api: {
    get: apiGetSpy,
    post: apiPostSpy,
  },
}));

vi.mock("@/api/hooks", () => ({
  useAdmins: () => ({ data: [{ username: "admin" }], isLoading: false }),
}));

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  haptic: () => {},
  openTelegramLink: vi.fn(),
}));

import { PinResetPaywallModal } from "./PinResetPaywallModal";

function renderModal(onPaid = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    onPaid,
    ...render(
      <QueryClientProvider client={qc}>
        <PinResetPaywallModal open onClose={() => {}} onPaid={onPaid} />
      </QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  apiGetSpy.mockReset();
  apiPostSpy.mockReset();
  toastSpy.mockClear();
});

describe("<PinResetPaywallModal />", () => {
  it("normalizes reset price currency codes before display", async () => {
    apiGetSpy.mockReturnValue({
      json: async () => ({
        price: "3.5",
        currency_code: " usd ",
        user_balance: "10",
        can_afford: true,
      }),
    });

    renderModal();

    expect(await screen.findByText("3.5 USD")).toBeInTheDocument();
    expect(screen.getByText("10 USD")).toBeInTheDocument();
    expect(screen.queryByText(/ usd /)).not.toBeInTheDocument();
  });

  it("does not render malformed reset price currency codes", async () => {
    apiGetSpy.mockReturnValue({
      json: async () => ({
        price: "3.5",
        currency_code: "../USD",
        user_balance: "10",
        can_afford: true,
      }),
    });

    renderModal();

    expect(await screen.findByText("3.5 USD")).toBeInTheDocument();
    expect(screen.getByText("10 USD")).toBeInTheDocument();
    expect(screen.queryByText(/\.\.\/USD/)).not.toBeInTheDocument();
  });

  it("renders malformed reset price payloads neutrally and disables balance payment", async () => {
    apiGetSpy.mockReturnValue({
      json: async () => ({
        price: "1e2",
        currency_code: "USD",
        user_balance: "0x10",
        can_afford: true,
      }),
    });

    const user = userEvent.setup();
    renderModal();

    expect(await screen.findByTestId("pin-reset-paywall")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText(/Не удалось проверить стоимость/)).toBeInTheDocument(),
    );
    expect(screen.getAllByText("\u2014 USD")).toHaveLength(2);
    expect(screen.queryByText(/1e2/)).not.toBeInTheDocument();
    expect(screen.queryByText(/0x10/)).not.toBeInTheDocument();

    const payButton = screen.getByRole("button", { name: /Оплатить с баланса/i });
    expect(payButton).toBeDisabled();
    await user.click(payButton);
    expect(apiPostSpy).not.toHaveBeenCalled();
  });

  it("does not render malformed charged amounts in the success toast", async () => {
    apiGetSpy.mockReturnValue({
      json: async () => ({
        price: "3.5",
        currency_code: "USD",
        user_balance: "10",
        can_afford: true,
      }),
    });
    apiPostSpy.mockReturnValue({
      json: async () => ({
        delivered: true,
        expires_at: "2026-01-01T00:00:00Z",
        charged: "1e2",
        currency_code: "USD",
      }),
    });

    const user = userEvent.setup();
    const onPaid = vi.fn();
    renderModal(onPaid);

    const payButton = await screen.findByRole("button", { name: /Оплатить с баланса/i });
    await waitFor(() => expect(payButton).toBeEnabled());
    await user.click(payButton);

    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "success",
          title: "Списано \u2014 USD",
        }),
      ),
    );
    expect(toastSpy).not.toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining("1e2") }),
    );
    expect(onPaid).toHaveBeenCalled();
  });

  it("normalizes paid currency codes in the success toast", async () => {
    apiGetSpy.mockReturnValue({
      json: async () => ({
        price: "3.5",
        currency_code: "USD",
        user_balance: "10",
        can_afford: true,
      }),
    });
    apiPostSpy.mockReturnValue({
      json: async () => ({
        delivered: true,
        expires_at: "2026-01-01T00:00:00Z",
        charged: "3.5",
        currency_code: "../USD",
      }),
    });

    const user = userEvent.setup();
    renderModal();

    const payButton = await screen.findByRole("button", { name: /Оплатить с баланса/i });
    await waitFor(() => expect(payButton).toBeEnabled());
    await user.click(payButton);

    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "success",
          title: expect.stringContaining("3.5 USD"),
        }),
      ),
    );
    expect(toastSpy).not.toHaveBeenCalledWith(
      expect.objectContaining({ title: expect.stringContaining("../USD") }),
    );
  });
});
