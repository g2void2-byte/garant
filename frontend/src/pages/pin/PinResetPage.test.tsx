import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PinStatusDto, PinTokenDto } from "@/api/types";

/**
 * Tests for the standalone `/pin/reset` flow (from settings).
 *
 * Step machine: request → code → new → confirm.
 * Covers: requestReset success (delivered=true info toast), undelivered
 * error toast, code input filter & gating, mismatched new PIN
 * rollback, happy-path confirmReset that calls setPinToken and
 * navigates back to /profile/settings.
 */

const mockState = vi.hoisted(() => ({
  requestReset: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  confirmReset: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  pinStatusData: { attempts_left: 3 } as Partial<PinStatusDto> | undefined,
}));

vi.mock("@/api/hooks", () => ({
  useRequestPinReset: () => mockState.requestReset,
  useConfirmPinReset: () => mockState.confirmReset,
  usePinStatus: () => ({ data: mockState.pinStatusData, isLoading: false }),
}));

const setPinTokenSpy = vi.hoisted(() => vi.fn());
vi.mock("@/lib/pin", () => ({
  setPinToken: setPinTokenSpy,
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  haptic: () => {},
  showBackButton: () => () => {},
}));

import PinResetPage from "./PinResetPage";

function LocationProbe() {
  const loc = useLocation();
  return <span data-testid="path">{loc.pathname}</span>;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/pin/reset"]}>
        <PinResetPage />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function clickDigits(
  user: ReturnType<typeof userEvent.setup>,
  digits: string,
) {
  for (const d of digits) {
    await user.click(screen.getByRole("button", { name: d }));
  }
}

beforeEach(() => {
  mockState.requestReset = { mutateAsync: vi.fn(), isPending: false };
  mockState.confirmReset = { mutateAsync: vi.fn(), isPending: false };
  mockState.pinStatusData = { attempts_left: 3 };
  setPinTokenSpy.mockClear();
  toastSpy.mockClear();
});

describe("<PinResetPage />", () => {
  it("renders the request step with explanatory subtitle and a button", () => {
    renderPage();
    expect(screen.getByText("Сброс PIN-кода")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Запросить код" }),
    ).toBeInTheDocument();
  });

  it("request happy path: delivered=true → info toast + move to code step", async () => {
    mockState.requestReset.mutateAsync.mockResolvedValue({ delivered: true });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Запросить код" }));
    await waitFor(() => expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "info" }),
    ));
    expect(await screen.findByText("Введите код")).toBeInTheDocument();
  });

  it("undelivered: shows error toast suggesting /start", async () => {
    mockState.requestReset.mutateAsync.mockResolvedValue({ delivered: false });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Запросить код" }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          body: expect.stringContaining("/start"),
        }),
      ),
    );
  });

  it("request failure surfaces an error toast", async () => {
    mockState.requestReset.mutateAsync.mockRejectedValue(new Error("nope"));
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Запросить код" }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "error", title: "nope" }),
      ),
    );
  });

  it("code input filters non-digits and caps at 6; continue is gated", async () => {
    mockState.requestReset.mutateAsync.mockResolvedValue({ delivered: true });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Запросить код" }));
    const input = (await screen.findByPlaceholderText(
      "000000",
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "abc12_345678" } });
    expect(input.value).toBe("123456");
    const cont = screen.getByRole("button", { name: "Продолжить" });
    expect(cont).not.toBeDisabled();
  });

  it("hides malformed attempts_left values on the code step", async () => {
    mockState.requestReset.mutateAsync.mockResolvedValue({ delivered: true });
    mockState.pinStatusData = { attempts_left: Number.NaN };
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Запросить код" }));
    expect(await screen.findByText("Введите код")).toBeInTheDocument();
    expect(screen.queryByTestId("pin-reset-attempts-left")).not.toBeInTheDocument();
    expect(screen.queryByText(/NaN/)).not.toBeInTheDocument();
  });

  it("happy path: code → matching new pins → confirmReset → navigate", async () => {
    mockState.requestReset.mutateAsync.mockResolvedValue({ delivered: true });
    const token: PinTokenDto = {
      token: "tok-1",
      expires_at: "2026-01-01T00:00:00Z",
    };
    mockState.confirmReset.mutateAsync.mockResolvedValue(token);
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Запросить код" }));
    const codeInput = (await screen.findByPlaceholderText(
      "000000",
    )) as HTMLInputElement;
    fireEvent.change(codeInput, { target: { value: "123456" } });
    await user.click(screen.getByRole("button", { name: "Продолжить" }));

    await clickDigits(user, "9876");
    expect(await screen.findByText("Подтвердите PIN")).toBeInTheDocument();
    await clickDigits(user, "9876");

    await waitFor(() =>
      expect(mockState.confirmReset.mutateAsync).toHaveBeenCalledWith({
        code: "123456",
        new_pin: "9876",
      }),
    );
    expect(setPinTokenSpy).toHaveBeenCalledWith(
      "tok-1",
      "2026-01-01T00:00:00Z",
    );
    await waitFor(() =>
      expect(screen.getByTestId("path").textContent).toBe(
        "/profile/settings",
      ),
    );
  });

  it("new-PIN mismatch in confirm step rolls back + error toast", async () => {
    mockState.requestReset.mutateAsync.mockResolvedValue({ delivered: true });
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Запросить код" }));
    const codeInput = (await screen.findByPlaceholderText(
      "000000",
    )) as HTMLInputElement;
    fireEvent.change(codeInput, { target: { value: "111222" } });
    await user.click(screen.getByRole("button", { name: "Продолжить" }));

    await clickDigits(user, "1111");
    await clickDigits(user, "2222");
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "error", title: "PIN не совпадает" }),
      ),
    );
    expect(mockState.confirmReset.mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText("Новый PIN")).toBeInTheDocument();
  });

  it("confirm failure resets to code step with error toast", async () => {
    mockState.requestReset.mutateAsync.mockResolvedValue({ delivered: true });
    mockState.confirmReset.mutateAsync.mockRejectedValueOnce(
      new Error("expired"),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole("button", { name: "Запросить код" }));
    const codeInput = (await screen.findByPlaceholderText(
      "000000",
    )) as HTMLInputElement;
    fireEvent.change(codeInput, { target: { value: "654321" } });
    await user.click(screen.getByRole("button", { name: "Продолжить" }));
    await clickDigits(user, "1234");
    await clickDigits(user, "1234");

    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({ kind: "error", title: "expired" }),
      ),
    );
    expect(await screen.findByText("Введите код")).toBeInTheDocument();
  });
});
