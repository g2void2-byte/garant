import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const apiPost = vi.hoisted(() => vi.fn());
const setTotpSessionToken = vi.hoisted(() => vi.fn());
const toastSpy = vi.hoisted(() => vi.fn());

vi.mock("@/api/client", () => ({
  api: { post: apiPost },
  TOTP_NOT_CONFIGURED_EVENT: "garant:totp-not-configured-test",
  TOTP_REQUIRED_EVENT: "garant:totp-required-test",
}));

vi.mock("@/components/ui/Toast", () => ({
  useToast: () => ({ show: toastSpy }),
}));

vi.mock("@/lib/totp", () => ({
  setTotpSessionToken,
}));

import { TOTP_REQUIRED_EVENT } from "@/api/client";
import { TotpGate } from "./TotpGate";

function renderGate() {
  return render(
    <MemoryRouter>
      <TotpGate />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  apiPost.mockReset();
  setTotpSessionToken.mockReset();
  toastSpy.mockReset();
});

describe("<TotpGate />", () => {
  it("accepts only the first 6 digits before opening a TOTP session", async () => {
    apiPost.mockReturnValue({
      json: vi.fn().mockResolvedValue({
        token: "totp-token",
        expires_at: "2026-06-03T00:00:00Z",
      }),
    });
    renderGate();

    window.dispatchEvent(new Event(TOTP_REQUIRED_EVENT));

    const input = await screen.findByPlaceholderText("123456");
    fireEvent.change(input, { target: { value: "12 34abc5678" } });

    expect(input).toHaveValue("123456");

    fireEvent.click(screen.getByRole("button", { name: "Подтвердить" }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("api/admin/2fa/session", {
        json: { code: "123456" },
      }),
    );
    expect(setTotpSessionToken).toHaveBeenCalledWith(
      "totp-token",
      "2026-06-03T00:00:00Z",
    );
  });
});
