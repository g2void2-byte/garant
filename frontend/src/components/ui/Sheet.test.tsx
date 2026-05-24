import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { Sheet } from "./Sheet";

/**
 * Tests for the bottom-sheet primitive.
 *
 * Pinned behaviour:
 *   - Mount lifecycle (``mounted`` vs ``visible``) — the sheet remains
 *     in the DOM during its 300ms close animation but its
 *     ``data-state`` flips to ``"closed"`` so consumers can target the
 *     final frame.
 *   - The scrollable body opts into ``touch-action: pan-y`` so the
 *     inner overflow works under Telegram WebView's iOS quirks even
 *     when ``body.style.overflow = "hidden"`` is set elsewhere
 *     (``AdminMenu``).
 *   - Backdrop click + Escape key fire ``onClose`` so the consumer can
 *     drive the close transition deterministically.
 */

describe("<Sheet />", () => {
  it("does not render when closed and never opened", () => {
    const { container } = render(
      <Sheet open={false} onClose={() => {}}>
        <div>hidden</div>
      </Sheet>,
    );
    expect(container.firstChild).toBeNull();
    expect(screen.queryByTestId("sheet")).not.toBeInTheDocument();
  });

  it("renders with data-state=open + pan-y touch action when open", () => {
    render(
      <Sheet open onClose={() => {}} title="Hello">
        <div>panel content</div>
      </Sheet>,
    );
    const sheet = screen.getByTestId("sheet");
    expect(sheet).toHaveAttribute("data-state", "open");
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("panel content")).toBeInTheDocument();

    // The body scroll container must expose ``touch-action: pan-y``
    // — the property survives the Tailwind class soup as an inline
    // style so it can't be silently dropped by class-merging.
    const scroller = Array.from(sheet.children).find(
      (el) => (el as HTMLElement).style.touchAction === "pan-y",
    ) as HTMLElement | undefined;
    expect(scroller).toBeDefined();
    expect(scroller).toHaveClass("overflow-y-auto");
  });

  it("fires onClose when the backdrop is clicked", () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose}>
        <div>body</div>
      </Sheet>,
    );

    // Backdrop is the first sibling of the panel — match by class.
    const backdrop = document.querySelector(
      ".fixed.inset-0.bg-black\\/60",
    ) as HTMLElement;
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("fires onClose on Escape", () => {
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose}>
        <div>body</div>
      </Sheet>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  describe("Telegram viewport (V13.2)", () => {
    afterEach(() => {
      // Tests below mutate ``window.Telegram``; clean up so the next
      // test (or test file) starts from a pristine non-Telegram
      // environment matching the regular jsdom default.
      delete (window as unknown as { Telegram?: unknown }).Telegram;
    });

    it("falls back to CSS dvh classes outside Telegram", () => {
      render(
        <Sheet open onClose={() => {}}>
          <div>body</div>
        </Sheet>,
      );
      const sheet = screen.getByTestId("sheet");
      // No Telegram → ``style`` is empty, the dvh fallback classes
      // are present so a plain browser tab still renders sensibly.
      expect(sheet.getAttribute("style") ?? "").toBe("");
      expect(sheet.className).toMatch(/max-h-\[min\(92dvh,92vh\)\]/);
    });

    it("derives style.maxHeight/minHeight from Telegram viewport", () => {
      // Minimal stub: only the bits ``useTelegramViewport`` touches.
      // ``viewportStableHeight`` takes precedence so the sheet
      // doesn't flicker between the soft-keyboard-open and
      // soft-keyboard-closed measurements on mobile.
      const expand = vi.fn();
      (window as unknown as { Telegram: { WebApp: unknown } }).Telegram = {
        WebApp: {
          viewportHeight: 600,
          viewportStableHeight: 800,
          expand,
          onEvent: vi.fn(),
          offEvent: vi.fn(),
          // Stub the rest of the surface that ``Sheet``'s imports
          // pull through — they're not exercised here but the
          // TypeScript shape demands their presence at runtime when
          // jsdom evaluates the module.
          BackButton: { show: vi.fn(), hide: vi.fn(), onClick: vi.fn(), offClick: vi.fn() },
          MainButton: {
            setText: vi.fn(),
            show: vi.fn(),
            hide: vi.fn(),
            onClick: vi.fn(),
            offClick: vi.fn(),
            enable: vi.fn(),
            disable: vi.fn(),
            showProgress: vi.fn(),
            hideProgress: vi.fn(),
            setParams: vi.fn(),
          },
          HapticFeedback: {
            impactOccurred: vi.fn(),
            notificationOccurred: vi.fn(),
            selectionChanged: vi.fn(),
          },
          initDataUnsafe: {},
          themeParams: {},
          ready: vi.fn(),
          close: vi.fn(),
          isExpanded: true,
          openTelegramLink: vi.fn(),
          openLink: vi.fn(),
        },
      };

      render(
        <Sheet open onClose={() => {}}>
          <div>body</div>
        </Sheet>,
      );
      const sheet = screen.getByTestId("sheet");
      // 800 * 0.92 = 736, 800 * 0.5 = 400. Sheet must use the
      // ``viewportStableHeight`` value, not ``viewportHeight``.
      expect(sheet.style.maxHeight).toBe("736px");
      expect(sheet.style.minHeight).toBe("400px");
      // Calling ``expand`` once at mount is what unfreezes the
      // iframe height in Telegram Desktop.
      expect(expand).toHaveBeenCalled();
      // The CSS dvh fallback must NOT also be applied — otherwise
      // a stale ``100dvh`` class would race the inline style and
      // re-introduce the original "sheet floats off-screen" bug.
      expect(sheet.className).not.toMatch(/max-h-\[min\(92dvh,92vh\)\]/);
    });
  });
});
