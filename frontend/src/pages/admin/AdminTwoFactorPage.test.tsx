import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Tests for `/admin/2fa` enrolment / removal page.
 *
 * Covers the three states (no 2FA → setup pending → enabled), the
 * secret/otpauth display, the 6-digit code gate on enable/disable, and
 * the `useAdminRedirect` gate.
 */

const mockState = vi.hoisted(() => ({
  status: { enabled: false } as { enabled: boolean },
  setupMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  enableMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  disableMutation: {
    mutateAsync: vi.fn() as ReturnType<typeof vi.fn>,
    isPending: false,
  },
  shouldRender: true as boolean,
}));

vi.mock("@/api/admin/hooks", () => ({
  useAdmin2faStatus: () => ({ data: mockState.status }),
  useAdmin2faSetup: () => mockState.setupMutation,
  useAdmin2faEnable: () => mockState.enableMutation,
  useAdmin2faDisable: () => mockState.disableMutation,
}));

vi.mock("@/hooks/useAdminRedirect", () => ({
  useAdminRedirect: () => ({ shouldRender: mockState.shouldRender }),
}));

const toastSpy = vi.hoisted(() => vi.fn());
vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

import AdminTwoFactorPage from "./AdminTwoFactorPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AdminTwoFactorPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  toastSpy.mockClear();
  mockState.status = { enabled: false };
  mockState.setupMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
  mockState.enableMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
  mockState.disableMutation = {
    mutateAsync: vi.fn(),
    isPending: false,
  };
  mockState.shouldRender = true;
});

describe("<AdminTwoFactorPage />", () => {
  it("returns null when admin guard rejects the visitor", () => {
    mockState.shouldRender = false;
    const { container } = renderPage();
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the 'не настроена' state and the setup button", () => {
    renderPage();
    expect(screen.getByText("2FA не настроена")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Включить 2FA/ })).toBeInTheDocument();
  });

  it("renders the 'активна' state when status.enabled is true", () => {
    mockState.status = { enabled: true };
    renderPage();
    expect(screen.getByText(/2FA активна для вашего аккаунта/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Включить 2FA/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отключить" })).toBeInTheDocument();
  });

  it("clicking 'Включить' shows the secret + otpauth and a 6-digit code input", async () => {
    mockState.setupMutation.mutateAsync.mockResolvedValue({
      secret: "JBSWY3DPEHPK3PXP",
      otpauth_url: "otpauth://totp/garant:admin?secret=JBSW",
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Включить 2FA/ }));
    await waitFor(() =>
      expect(screen.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument(),
    );
    expect(screen.getByText(/otpauth:\/\/totp\/garant:admin/)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("123 456"),
    ).toBeInTheDocument();
  });

  it("setup failure surfaces a toast and does not reveal a secret", async () => {
    mockState.setupMutation.mutateAsync.mockRejectedValueOnce(
      new Error("ALREADY_ENABLED"),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Включить 2FA/ }));
    await waitFor(() =>
      expect(toastSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          kind: "error",
          body: "ALREADY_ENABLED",
        }),
      ),
    );
  });

  it("confirm button stays disabled until the code has 6 digits", async () => {
    mockState.setupMutation.mutateAsync.mockResolvedValue({
      secret: "ABCDEFGHIJKLMNOP",
      otpauth_url: "otpauth://totp/garant:admin?secret=ABC",
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Включить 2FA/ }));
    const confirm = await screen.findByRole("button", { name: "Подтвердить" });
    expect(confirm).toBeDisabled();

    const codeInput = screen.getByPlaceholderText("123 456");
    fireEvent.change(codeInput, { target: { value: "123" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(codeInput, { target: { value: "123456" } });
    expect(confirm).not.toBeDisabled();
  });

  it("enable input keeps only the first 6 digits", async () => {
    mockState.setupMutation.mutateAsync.mockResolvedValue({
      secret: "ABCDEFGHIJKLMNOP",
      otpauth_url: "otpauth://totp/garant:admin?secret=ABC",
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Включить 2FA/ }));
    const codeInput = await screen.findByPlaceholderText("123 456");

    fireEvent.change(codeInput, { target: { value: "12 34abc5678" } });

    expect(codeInput).toHaveValue("123456");
  });

  it("confirm passes secret + code and toasts on success", async () => {
    mockState.setupMutation.mutateAsync.mockResolvedValue({
      secret: "TESTSECRET00",
      otpauth_url: "otpauth://x",
    });
    mockState.enableMutation.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: /Включить 2FA/ }));
    const codeInput = await screen.findByPlaceholderText("123 456");
    fireEvent.change(codeInput, { target: { value: "987654" } });
    await user.click(screen.getByRole("button", { name: "Подтвердить" }));
    await waitFor(() =>
      expect(mockState.enableMutation.mutateAsync).toHaveBeenCalledWith({
        secret: "TESTSECRET00",
        code: "987654",
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "success", title: "2FA включена" }),
    );
  });

  it("disable flow gates on a 6-digit code and toasts on success", async () => {
    mockState.status = { enabled: true };
    mockState.disableMutation.mutateAsync.mockResolvedValue({});
    const user = userEvent.setup();
    renderPage();

    const disableBtn = screen.getByRole("button", { name: "Отключить" });
    expect(disableBtn).toBeDisabled();

    const codeInput = screen.getByPlaceholderText("123 456");
    fireEvent.change(codeInput, { target: { value: "111 2227" } });
    await user.click(screen.getByRole("button", { name: "Отключить" }));
    await waitFor(() =>
      expect(mockState.disableMutation.mutateAsync).toHaveBeenCalledWith({
        code: "111222",
      }),
    );
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "info", title: "2FA отключена" }),
    );
  });

  it("copy button writes the secret into the clipboard and shows toast", async () => {
    mockState.setupMutation.mutateAsync.mockResolvedValue({
      secret: "COPYME12345",
      otpauth_url: "otpauth://x",
    });
    const user = userEvent.setup();
    // `userEvent.setup()` installs a jsdom clipboard polyfill on
    // `navigator.clipboard`, so spy on the already-installed writeText.
    const writeSpy = vi.spyOn(navigator.clipboard, "writeText");
    const { container } = renderPage();

    await user.click(screen.getByRole("button", { name: /Включить 2FA/ }));
    await screen.findByText("COPYME12345");
    const secretRow = container.querySelector(
      "div.bg-panel-2.rounded-button.p-2",
    ) as HTMLElement | null;
    expect(secretRow).not.toBeNull();
    const copyBtn = secretRow!.querySelector(
      "button",
    ) as HTMLButtonElement | null;
    expect(copyBtn).not.toBeNull();
    copyBtn!.click();
    expect(writeSpy).toHaveBeenCalledWith("COPYME12345");
    expect(toastSpy).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "info", title: "Скопировано" }),
    );
    writeSpy.mockRestore();
  });
});
