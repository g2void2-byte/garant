import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AccountTransferStatusDto } from "@/api/types";

/**
 * Tests for the "Перенос аккаунта" page that lets a user migrate
 * their Garant profile to a different Telegram account.
 *
 * Covers:
 *   - status hint when an active code already exists
 *   - "Send" tab: start / cancel buttons + their toast / haptic
 *     side-effects
 *   - "Receive" tab: policy-length code validation + happy path that
 *     clears the PIN token and navigates to /profile
 *   - non-numeric input is stripped and capped at the configured length
 */

const transferPolicy = { code_length: 6, ttl_seconds: 15 * 60 };

const mockState = vi.hoisted(() => ({
  status: {
    has_active: false,
    expires_at: null,
    code_length: 6,
    ttl_seconds: 15 * 60,
  } as AccountTransferStatusDto,
  start: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  cancel: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  confirm: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
}));

vi.mock("@/api/hooks", () => ({
  useAccountTransferStatus: () => ({ data: mockState.status }),
  useStartAccountTransfer: () => mockState.start,
  useCancelAccountTransfer: () => mockState.cancel,
  useConfirmAccountTransfer: () => mockState.confirm,
}));

const clearPinTokenSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/pin", () => ({
  clearPinToken: clearPinTokenSpy,
}));

const hapticSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: hapticSpy,
  showBackButton: () => () => {},
}));

import AccountTransferPage from "./AccountTransferPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AccountTransferPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  hapticSpy.mockClear();
  clearPinTokenSpy.mockClear();
  mockState.status = { has_active: false, expires_at: null, ...transferPolicy };
  mockState.start = { mutateAsync: vi.fn(), isPending: false };
  mockState.cancel = { mutateAsync: vi.fn(), isPending: false };
  mockState.confirm = { mutateAsync: vi.fn(), isPending: false };
});

describe("<AccountTransferPage />", () => {
  it("renders malformed active expiry without a NaN countdown", () => {
    mockState.status = {
      has_active: true,
      expires_at: "not-a-date",
      ...transferPolicy,
    };
    renderPage();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
    expect(
      screen.queryAllByText((_, element) => Boolean(element?.textContent?.includes("\u2014."))).length,
    ).toBeGreaterThan(0);
  });

  it("falls back to safe policy values for malformed runtime length and ttl", async () => {
    mockState.status = {
      has_active: false,
      expires_at: null,
      code_length: "1e2" as unknown as number,
      ttl_seconds: "0x10" as unknown as number,
    };
    const user = userEvent.setup();
    renderPage();
    expect(document.body.textContent).toContain("15 ");

    await user.click(screen.getByRole("button", { name: /\u0412\u0432\u0435\u0441\u0442\u0438 \u043a\u043e\u0434/ }));
    const input = screen.getByPlaceholderText("000000") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "1234567" } });
    expect(input.value).toBe("123456");
    expect(
      screen.getByRole("button", {
        name: /\u041f\u0435\u0440\u0435\u043d\u0435\u0441\u0442\u0438 \u0430\u043a\u043a\u0430\u0443\u043d\u0442/,
      }),
    ).not.toBeDisabled();
  });

  it("does not let a zero-length runtime policy enable empty-code confirm", async () => {
    mockState.status = {
      has_active: false,
      expires_at: null,
      code_length: 0,
      ttl_seconds: 0,
    };
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /\u0412\u0432\u0435\u0441\u0442\u0438 \u043a\u043e\u0434/ }));
    expect(screen.getByPlaceholderText("000000")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: /\u041f\u0435\u0440\u0435\u043d\u0435\u0441\u0442\u0438 \u0430\u043a\u043a\u0430\u0443\u043d\u0442/,
      }),
    ).toBeDisabled();
  });

  it("renders the header and 'Send' tab by default", () => {
    renderPage();
    expect(
      screen.getByRole("heading", { name: "Перенос аккаунта" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Выпустить код/ }),
    ).toBeInTheDocument();
  });

  it("shows 'Код уже выпущен' when has_active=true and disables cancel only when no code", () => {
    mockState.status = {
      has_active: true,
      expires_at: new Date(Date.now() + 8 * 60_000).toISOString(),
      ...transferPolicy,
    };
    renderPage();
    expect(screen.getByText("Код уже выпущен")).toBeInTheDocument();
    // The "Выпустить" copy switches to "Выпустить новый".
    expect(
      screen.getByRole("button", { name: /Выпустить новый/ }),
    ).toBeInTheDocument();
    const cancel = screen.getByRole("button", { name: /Отменить/ });
    expect(cancel).not.toBeDisabled();
  });

  it("happy path: start succeeds with delivered=true -> haptic('success')", async () => {
    mockState.start.mutateAsync.mockResolvedValue({
      delivered: true,
      expires_at: new Date().toISOString(),
      ...transferPolicy,
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Выпустить код/ }));
    await waitFor(() => {
      expect(mockState.start.mutateAsync).toHaveBeenCalled();
    });
    expect(hapticSpy).toHaveBeenCalledWith("success");
  });

  it("start failure -> haptic('error')", async () => {
    mockState.start.mutateAsync.mockRejectedValue(new Error("Лимит"));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Выпустить код/ }));
    await waitFor(() => {
      expect(hapticSpy).toHaveBeenCalledWith("error");
    });
  });

  it("cancel succeeds + fires haptic('success')", async () => {
    mockState.status = {
      has_active: true,
      expires_at: new Date(Date.now() + 5 * 60_000).toISOString(),
      ...transferPolicy,
    };
    mockState.cancel.mutateAsync.mockResolvedValue({ ok: true });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: /Отменить/ }));
    await waitFor(() => {
      expect(mockState.cancel.mutateAsync).toHaveBeenCalled();
    });
    expect(hapticSpy).toHaveBeenCalledWith("success");
  });

  it("'Receive' tab: blocks confirm until the code matches policy length", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Ввести код" }));
    // Without entering anything, the confirm button is disabled.
    const confirm = screen.getByRole("button", { name: /Перенести аккаунт/ });
    expect(confirm).toBeDisabled();
    expect(mockState.confirm.mutateAsync).not.toHaveBeenCalled();
  });

  it("'Receive' tab strips non-digits and caps the input at the configured length", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Ввести код" }));
    const input = screen.getByPlaceholderText("000000") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "1a2b3c4d5e6f7g" } });
    expect(input.value).toBe("123456");
    expect(screen.getByRole("button", { name: /Перенести аккаунт/ })).not.toBeDisabled();
  });

  it("'Receive' tab happy path: confirms + clears PIN + fires haptic('success')", async () => {
    mockState.confirm.mutateAsync.mockResolvedValue({ ok: true, tg_user_id: 1001 });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Ввести код" }));
    const input = screen.getByPlaceholderText("000000") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "123456" } });
    // ``fireEvent.click`` avoids userEvent's pointer/event-loop dance,
    // which interacts badly with the 15s ``setInterval`` mounted by
    // the component.
    fireEvent.click(
      screen.getByRole("button", { name: /Перенести аккаунт/ }),
    );

    await waitFor(() => {
      expect(mockState.confirm.mutateAsync).toHaveBeenCalledWith("123456");
    });
    expect(clearPinTokenSpy).toHaveBeenCalled();
    expect(hapticSpy).toHaveBeenCalledWith("success");
  });

  it("'Receive' tab error path: surfaces server message via haptic('error')", async () => {
    mockState.confirm.mutateAsync.mockRejectedValue(new Error("Код не подошёл"));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Ввести код" }));
    const input = screen.getByPlaceholderText("000000") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "999999" } });
    fireEvent.click(
      screen.getByRole("button", { name: /Перенести аккаунт/ }),
    );
    await waitFor(() => {
      expect(hapticSpy).toHaveBeenCalledWith("error");
    });
    expect(clearPinTokenSpy).not.toHaveBeenCalled();
  });
});
