import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MinimizeButton } from "./MinimizeButton";

vi.mock("@/lib/tg", () => ({
  useTelegramViewport: () => null,
  isMobile: vi.fn(),
  minimizeApp: vi.fn(),
  haptic: vi.fn(),
}));

import { haptic, isMobile, minimizeApp } from "@/lib/tg";

afterEach(() => {
  vi.mocked(isMobile).mockReset();
  vi.mocked(minimizeApp).mockReset();
  vi.mocked(haptic).mockReset();
});

describe("<MinimizeButton />", () => {
  it("renders on mobile and calls minimizeApp on click", () => {
    vi.mocked(isMobile).mockReturnValue(true);

    render(<MinimizeButton />);
    const btn = screen.getByRole("button", { name: /Свернуть/i });
    expect(btn).toBeInTheDocument();

    fireEvent.click(btn);
    expect(minimizeApp).toHaveBeenCalledTimes(1);
    expect(haptic).toHaveBeenCalledWith("light");
  });

  it("renders nothing on desktop / non-mobile platforms", () => {
    vi.mocked(isMobile).mockReturnValue(false);

    const { container } = render(<MinimizeButton />);
    expect(container).toBeEmptyDOMElement();
  });
});
